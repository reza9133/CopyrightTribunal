# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
import json
import re
import typing
from datetime import datetime, timezone
from dataclasses import dataclass

# Limits - 32MB to handle large web pages safely
MAX_ID_LENGTH = 64
MAX_URL_LENGTH = 512
MAX_DOC_BYTES = 33554432  # 32 MB
MAX_MODEL_OUTPUT = 2048

# Verdict Enums
VERDICT_INFRINGEMENT = "INFRINGEMENT_FOUND"
VERDICT_CLEARED = "CLEARED"
VERDICT_UNRESOLVED = "UNRESOLVED"
ALLOWED_VERDICTS = {VERDICT_INFRINGEMENT, VERDICT_CLEARED, VERDICT_UNRESOLVED}

# Lifecycle States
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

def _fetch_document(url: str) -> str:
    response = gl.nondet.web.get(url)
    status = getattr(response, "status", getattr(response, "status_code", None))
    
    if status != 200 or response.body is None:
        raise gl.vm.UserError(f"Failed to retrieve document from {url}")

    body = response.body if isinstance(response.body, bytes) else response.body.encode("utf-8")
    
    if len(body) > MAX_DOC_BYTES:
        raise gl.vm.UserError("Document size exceeds maximum allowed bytes")

    return body.decode("utf-8")


class CopyrightTribunal(gl.Contract):
    assets: TreeMap[str, CopyrightAsset]
    disputes: TreeMap[str, DisputeCase]

    def __init__(self):
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

        def leader_fn() -> str:
            original_text = _fetch_document(original_url_copy)
            claimant_text = _fetch_document(claimant_url_copy)

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
            - "verdict": If score > 30, return "INFRINGEMENT_FOUND". Otherwise return "CLEARED".
            - "reasoning": A brief explanation of the overlapping patterns.
            
            Output ONLY valid JSON. No markdown formatting, no code blocks.
            """
            model_out = gl.nondet.exec_prompt(prompt, response_format="json")
            
            try:
                # دیباگ ۱: بررسی نوع خروجی مدل (جلوگیری از خطای dict object has no attribute strip)
                if isinstance(model_out, dict):
                    data = model_out
                else:
                    cleaned_out = str(model_out).strip()
                    if cleaned_out.startswith("```"):
                        cleaned_out = re.sub(r"^```(?:json)?\s*", "", cleaned_out)
                        cleaned_out = re.sub(r"\s*```$", "", cleaned_out)
                    
                    first_brace = cleaned_out.find("{")
                    last_brace = cleaned_out.rfind("}")
                    if first_brace != -1 and last_brace != -1:
                        cleaned_out = cleaned_out[first_brace:last_brace + 1]

                    data = json.loads(cleaned_out)

                score = int(data.get("similarity_score", 0))
                verdict = str(data.get("verdict", VERDICT_UNRESOLVED))
                
                if verdict not in ALLOWED_VERDICTS:
                    verdict = VERDICT_UNRESOLVED
                    
                normalized = json.dumps({
                    "similarity_score": max(0, min(100, score)),
                    "verdict": verdict
                }, separators=(",", ":"), sort_keys=True)
                return normalized
                
            except Exception as e:
                raise gl.vm.UserError(f"LLM output parsing failed: {str(e)}")

        def validator_fn(leader_result: typing.Any) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
                
            try:
                validator_json = leader_fn()
                val_data = json.loads(validator_json)
                lead_data = json.loads(leader_result.calldata)

                if val_data["verdict"] != lead_data["verdict"]:
                    return False

                val_score = val_data["similarity_score"]
                lead_score = lead_data["similarity_score"]
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
        dispute.resolution_date = self._get_timestamp()
        self.disputes[dispute_id] = dispute

        asset.state = STATE_RESOLVED
        self.assets[asset_id] = asset

    @gl.public.view
    def get_asset_status(self, asset_id: str) -> dict:
        _require(asset_id in self.assets, "Asset not found")
        a = self.assets[asset_id]
        return {
            "owner": str(a.owner),
            "state": a.state,
            "active_dispute_id": a.active_dispute_id
        }

    @gl.public.view
    def get_dispute_verdict(self, dispute_id: str) -> dict:
        _require(dispute_id in self.disputes, "Dispute not found")
        d = self.disputes[dispute_id]
        return {
            "similarity_score": int(d.similarity_score),
            "verdict": d.verdict,
            "resolution_date": int(d.resolution_date)
        }
