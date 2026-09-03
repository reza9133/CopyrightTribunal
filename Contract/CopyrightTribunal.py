# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
import json
import re
import typing
import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass

MAX_ID_LENGTH = 64
MAX_URL_LENGTH = 512
MAX_DOC_BYTES = 33554432

VERDICT_INFRINGEMENT = "INFRINGEMENT_FOUND"
VERDICT_CLEARED = "CLEARED"
VERDICT_UNRESOLVED = "UNRESOLVED"

STATE_REGISTERED = "REGISTERED"
STATE_DISPUTED = "DISPUTED"
STATE_RESOLVED = "RESOLVED"

@allow_storage
@dataclass
class CopyrightAsset:
    owner: Address
    original_url: str
    content_hash: str
    registration_date: u32
    state: str
    active_dispute_id: str

@allow_storage
@dataclass
class DisputeCase:
    claimant: Address
    claimant_url: str
    similarity_score: u8
    verdict: str
    resolution_date: u32

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise gl.vm.UserError(message)

def _validate_id(record_id: str) -> str:
    _require(isinstance(record_id, str), "ID must be a string")
    _require(1 <= len(record_id) <= MAX_ID_LENGTH, "Invalid ID length")
    _require(re.fullmatch(r"[a-zA-Z0-9_-]+", record_id) is not None, "Invalid ID format")
    return record_id

def _validate_url(url: str) -> str:
    _require(isinstance(url, str), "URL must be a string")
    _require(8 < len(url) <= MAX_URL_LENGTH, "URL length out of bounds")
    _require(url.startswith("https://"), "URL must strictly use HTTPS")
    return url

class CopyrightTribunal(gl.Contract):
    assets: TreeMap[str, CopyrightAsset]
    disputes: TreeMap[str, DisputeCase]

    def __init__(self):
        # GenVM automatically initializes Storage variables (like TreeMap and DynArray),
        # so manual initialization is not needed.
        pass

    def _get_timestamp(self) -> u32:
        return u32(int(datetime.now(timezone.utc).timestamp()))

    @gl.public.write
    def register_asset(self, asset_id: str, original_url: str, content_hash: str) -> None:
        asset_id = _validate_id(asset_id)
        original_url = _validate_url(original_url)
        _require(asset_id not in self.assets, "Asset ID already registered")

        self.assets[asset_id] = CopyrightAsset(
            owner=gl.message.sender_address,
            original_url=original_url,
            content_hash=content_hash,
            registration_date=self._get_timestamp(),
            state=STATE_REGISTERED,
            active_dispute_id=""
        )

    @gl.public.write
    def file_dispute(self, asset_id: str, dispute_id: str, claimant_url: str) -> None:
        asset_id = _validate_id(asset_id)
        dispute_id = _validate_id(dispute_id)
        claimant_url = _validate_url(claimant_url)

        _require(asset_id in self.assets, "Target Asset ID not found")
        _require(dispute_id not in self.disputes, "Dispute ID already exists")
        
        asset = self.assets[asset_id]
        _require(asset.state == STATE_REGISTERED, "Asset is already under dispute or resolved")

        asset.state = STATE_DISPUTED
        asset.active_dispute_id = dispute_id
        self.assets[asset_id] = asset

        self.disputes[dispute_id] = DisputeCase(
            claimant=gl.message.sender_address,
            claimant_url=claimant_url,
            similarity_score=u8(0),
            verdict=VERDICT_UNRESOLVED,
            resolution_date=u32(0)
        )

    @gl.public.write
    def adjudicate_dispute(self, asset_id: str) -> None:
        asset_id = _validate_id(asset_id)
        _require(asset_id in self.assets, "Asset not found")
        
        asset = self.assets[asset_id]
        _require(asset.state == STATE_DISPUTED, "Asset is not currently under dispute")
        
        dispute_id = asset.active_dispute_id
        dispute = self.disputes[dispute_id]

        original_url_copy = asset.original_url
        claimant_url_copy = dispute.claimant_url
        expected_hash = asset.content_hash

        def leader_fn() -> str:
            # Internal helper mapped safely inside the non-deterministic block
            def fetch_doc_internal(url: str) -> str:
                try:
                    response = gl.nondet.web.get(url)
                    status = getattr(response, "status", getattr(response, "status_code", None))
                    
                    if status != 200 or response.body is None:
                        return f"[FETCH_ERROR_STATUS_{status}]"

                    body = response.body
                    if not isinstance(body, bytes):
                        body = str(body).encode("utf-8")
                    
                    if len(body) > MAX_DOC_BYTES:
                        return "[FETCH_ERROR_TOO_LARGE]"

                    return body.decode("utf-8", errors="ignore")
                except Exception:
                    return "[FETCH_ERROR_EXCEPTION]"

            original_text = fetch_doc_internal(original_url_copy)
            
            if original_text.startswith("[FETCH_ERROR_"):
                return json.dumps({
                    "similarity_score": 0,
                    "verdict": VERDICT_UNRESOLVED,
                    "reasoning": "Original content unavailable due to network/server errors."
                }, separators=(",", ":"), sort_keys=True)

            # Programmatically check the original content hash
            current_hash = hashlib.sha256(original_text.encode('utf-8')).hexdigest()
            
            if current_hash != expected_hash:
                return json.dumps({
                    "similarity_score": 0,
                    "verdict": VERDICT_CLEARED,
                    "reasoning": "Original content hash mismatch. The registered content has been tampered with."
                }, separators=(",", ":"), sort_keys=True)

            claimant_text = fetch_doc_internal(claimant_url_copy)
            
            if claimant_text.startswith("[FETCH_ERROR_"):
                return json.dumps({
                    "similarity_score": 0,
                    "verdict": VERDICT_UNRESOLVED,
                    "reasoning": "Claimant content unavailable due to network/server errors."
                }, separators=(",", ":"), sort_keys=True)

            prompt = f"""
            You are a strict Copyright and Plagiarism Arbitrator.
            Compare the Original Registered Document with the Claimant's Suspected Document.
            
            === ORIGINAL DOCUMENT ===
            {original_text[:4000]}
            
            === CLAIMANT DOCUMENT ===
            {claimant_text[:4000]}
            
            Evaluate the structural and semantic similarity.
            Return a JSON object with EXACTLY these keys:
            - "similarity_score": Integer from 0 to 100 representing percentage of copied content.
            - "reasoning": A brief explanation of the overlapping patterns.
            
            Output ONLY valid JSON.
            """
            
            model_out = gl.nondet.exec_prompt(prompt, response_format="json")
            
            if not isinstance(model_out, dict):
                raise gl.vm.UserError("LLM did not return a valid dictionary structure.")
                
            try:
                raw_score = model_out.get("similarity_score", 0)
                score = int(str(raw_score).strip())
                score = max(0, min(100, score))
                
                # Enforce the decision rule programmatically
                calculated_verdict = VERDICT_INFRINGEMENT if score > 30 else VERDICT_CLEARED
                
                return json.dumps({
                    "similarity_score": score,
                    "verdict": calculated_verdict,
                    "reasoning": str(model_out.get("reasoning", ""))
                }, separators=(",", ":"), sort_keys=True)
                
            except Exception as e:
                raise gl.vm.UserError(f"LLM output structure invalid: {str(e)}")

        def validator_fn(leader_result: typing.Any) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                leader_msg = getattr(leader_result, 'message', str(leader_result))
                try:
                    leader_fn()
                    return False
                except gl.vm.UserError as e:
                    validator_msg = getattr(e, 'message', str(e))
                    return validator_msg == leader_msg
                except Exception:
                    return False
                
            try:
                validator_json = leader_fn()
                val_data = json.loads(validator_json)
                lead_data = json.loads(leader_result.calldata)

                # The final verdict must match exactly
                if val_data["verdict"] != lead_data["verdict"]:
                    return False

                val_score = val_data["similarity_score"]
                lead_score = lead_data["similarity_score"]
                
                # 5% tolerance for non-deterministic AI scoring differences
                if abs(val_score - lead_score) > 5:
                    return False

                return True
            except Exception:
                return False

        consensus_output_json = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        consensus_data = json.loads(consensus_output_json)

        final_verdict = consensus_data["verdict"]
        
        dispute.similarity_score = u8(consensus_data["similarity_score"])
        dispute.verdict = final_verdict
        
        if final_verdict != VERDICT_UNRESOLVED:
            dispute.resolution_date = self._get_timestamp()
            asset.state = STATE_RESOLVED
            self.assets[asset_id] = asset

        self.disputes[dispute_id] = dispute

    @gl.public.view
    def get_asset_status(self, asset_id: str) -> dict[str, str]:
        _require(asset_id in self.assets, "Asset not found")
        a = self.assets[asset_id]
        return {
            "owner": str(a.owner),
            "original_url": a.original_url,
            "content_hash": a.content_hash,
            "registration_date": str(a.registration_date),
            "state": a.state,
            "active_dispute_id": a.active_dispute_id
        }

    @gl.public.view
    def get_dispute_verdict(self, dispute_id: str) -> dict[str, str]:
        _require(dispute_id in self.disputes, "Dispute not found")
        d = self.disputes[dispute_id]
        return {
            "claimant": str(d.claimant),
            "claimant_url": d.claimant_url,
            "similarity_score": str(d.similarity_score),
            "verdict": d.verdict,
            "resolution_date": str(d.resolution_date)
        }
