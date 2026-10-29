import abc
import hashlib
import json
import logging
import re
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.config import settings
from app.modules.ai_assist.schemas.ai_assist import (
    DepartmentRouteResult,
    InterpretationResult,
    LanguageDetectResult,
    PriorityAssessmentResult,
)

logger = logging.getLogger("app.ai.providers")
T = TypeVar("T", bound=BaseModel)


class LLMProvider(abc.ABC):
    """Abstract interface for LLM text and structured output generation."""

    @abc.abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Generates plain text response."""
        pass

    @abc.abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_instruction: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        """Generates structured response validated against a Pydantic schema."""
        pass


class EmbeddingProvider(abc.ABC):
    """Abstract interface for generating vector embeddings."""

    @abc.abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Generates an embedding vector for a single string."""
        pass

    @abc.abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generates embedding vectors for a batch of strings."""
        pass


class MockProvider(LLMProvider, EmbeddingProvider):
    """Deterministic, keyword-based mock provider used in testing and offline environments."""

    def __init__(self) -> None:
        self.forced_confidence: float | None = None
        self.force_invalid_json: bool = False
        self.force_timeout: bool = False
        self.force_failure: bool = False
        self.last_prompt: str | None = None
        self.last_system_instruction: str | None = None
        self.call_count: int = 0

    def reset_mocks(self) -> None:
        self.forced_confidence = None
        self.force_invalid_json = False
        self.force_timeout = False
        self.force_failure = False
        self.last_prompt = None
        self.last_system_instruction = None
        self.call_count = 0

    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction

        if self.force_failure:
            raise RuntimeError("Mock provider simulated failure.")
        if self.force_timeout:
            import asyncio

            await asyncio.sleep(settings.AI_TIMEOUT_SECONDS + 1.0)
            raise TimeoutError("Mock provider simulated timeout.")
        if self.force_invalid_json:
            return "{ invalid_json: true, unterminated string"

        return "Mock response generated for prompt."

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_instruction: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction

        if self.force_failure:
            raise RuntimeError("Mock provider simulated failure.")
        if self.force_timeout:
            import asyncio

            await asyncio.sleep(settings.AI_TIMEOUT_SECONDS + 1.0)
            raise TimeoutError("Mock provider simulated timeout.")
        if self.force_invalid_json:
            raise ValueError("Malformed JSON returned by provider.")

        confidence = self.forced_confidence if self.forced_confidence is not None else 0.95
        p_lower = prompt.lower()
        confidence = self.forced_confidence if self.forced_confidence is not None else 0.95

        # Check for vague text patterns (triggers graceful degradation to MANUAL_TRIAGE)
        vague_markers = [
            "problem here",
            "something is wrong",
            "bad condition",
            "issue on street",
            "help needed",
            "समस्या है",
            "काम नहीं हो रहा है",
            "यहाँ हालत खराब है",
            "ಇಲ್ಲಿ ಸಮಸ್ಯೆ ಇದೆ",
            "ಸರಿಪಡಿಸಿ",
            "ಏನೋ ಆಗಿದೆ",
            "kuch theek nahi hai",
            "very bad service",
            "urgent inspection required",
            "please do the needful",
        ]
        is_vague = any(vm in p_lower for vm in vague_markers)
        if is_vague and self.forced_confidence is None:
            confidence = 0.50

        # Check for adversarial injection patterns
        adversarial_markers = [
            "ignore previous instructions",
            "system override",
            "forget your system",
            "drop table",
            "<script>",
            "cross-site scripting",
            "output json only",
            "what is your system prompt",
            "execute command",
            "jailbreak",
            "disregard safety",
            "पुरानी निर्देश भूल",
            "ಹಿಂದಿನ ಎಲ್ಲಾ ನಿಯಮಗಳನ್ನು ನಿರ್ಲಕ್ಷಿಸಿ",
        ]
        is_adversarial = any(am in p_lower for am in adversarial_markers)
        if is_adversarial and self.forced_confidence is None:
            confidence = 0.45

        # 1. Handle Language Detection
        if issubclass(schema, LanguageDetectResult):
            has_devanagari = any("\u0900" <= ch <= "\u097f" for ch in prompt)
            has_kannada = any("\u0c80" <= ch <= "\u0cff" for ch in prompt)

            code_mixed_markers = [
                "hai",
                "raha",
                "gaya",
                "kuch",
                "bohot",
                "dikkat",
                "karna",
                "raste",
                "alli",
                "aagide",
                "ide",
                "aagalla",
                "barthide",
                "maadi",
                "gundi",
                "hogiddare",
                "hattira",
                "karke",
                "pe",
                "mele",
                "pakka",
                "thilla",
                "nahi",
                "saath",
            ]
            has_code_mixed = any(
                re.search(rf"\b{m}\b", p_lower) for m in code_mixed_markers
            ) and not (has_devanagari or has_kannada)

            if has_devanagari:
                data = {
                    "language_code": "hi",
                    "language_name": "Hindi",
                    "confidence": confidence,
                    "requires_translation": True,
                    "translated_title": "Damaged Road on Main Street",
                    "translated_description": "There is a deep pothole or municipal issue.",
                }
            elif has_kannada:
                data = {
                    "language_code": "kn",
                    "language_name": "Kannada",
                    "confidence": confidence,
                    "requires_translation": True,
                    "translated_title": "Municipal Grievance in Kannada",
                    "translated_description": "Citizen reported municipal grievance in Kannada.",
                }
            elif has_code_mixed:
                data = {
                    "language_code": "code_mixed",
                    "language_name": "Code-Mixed",
                    "confidence": confidence,
                    "requires_translation": True,
                    "translated_title": "Code-Mixed Citizen Grievance",
                    "translated_description": "Citizen grievance in code-mixed dialect.",
                }
            else:
                data = {
                    "language_code": "en",
                    "language_name": "English",
                    "confidence": confidence,
                    "requires_translation": False,
                    "translated_title": "Citizen Grievance Title",
                    "translated_description": "Citizen Grievance Description",
                }
            return schema.model_validate(data)

        # 2. Handle Department Routing
        if issubclass(schema, DepartmentRouteResult):
            if any(
                k in p_lower
                for k in [
                    "light",
                    "dark",
                    "pole",
                    "lamp",
                    "wire",
                    "electric",
                    "transformer",
                    "बिजली",
                    "खंभा",
                    "तार",
                    "ದೀಪ",
                    "ಕಂಬ",
                    "ವಿದ್ಯುತ್",
                ]
            ):
                dept = "Electricity and Street Lighting"
            elif any(
                k in p_lower
                for k in [
                    "water",
                    "leak",
                    "pipe",
                    "drinking",
                    "tap",
                    "meter",
                    "पानी",
                    "पाइप",
                    "नल",
                    "ನೀರು",
                    "ನಲ್ಲಿ",
                ]
            ):
                dept = "Water and Sewage"
            elif any(
                k in p_lower
                for k in [
                    "garbage",
                    "trash",
                    "waste",
                    "bin",
                    "dump",
                    "debris",
                    "dustbin",
                    "carcass",
                    "कचरा",
                    "कूड़ा",
                    "मलबा",
                    "ಕಸ",
                    "ತ್ಯಾಜ್ಯ",
                ]
            ):
                dept = "Sanitation and Waste Management"
            elif any(
                k in p_lower
                for k in [
                    "drain",
                    "gutter",
                    "flood",
                    "stormwater",
                    "sewage",
                    "manhole",
                    "waterlogging",
                    "नाली",
                    "सीवर",
                    "मैनहोल",
                    "ಚರಂಡಿ",
                ]
            ):
                dept = "Stormwater Drainage"
            elif any(
                k in p_lower
                for k in [
                    "park",
                    "tree",
                    "bench",
                    "swing",
                    "garden",
                    "lawn",
                    "branch",
                    "पार्क",
                    "पेड़",
                    "घास",
                    "झूला",
                    "ಉದ್ಯಾನ",
                    "ಮರ",
                    "ಹುಲ್ಲು",
                ]
            ):
                dept = "Parks and Horticulture"
            elif any(
                k in p_lower
                for k in [
                    "pothole",
                    "crater",
                    "road",
                    "footpath",
                    "tar",
                    "asphalt",
                    "divider",
                    "median",
                    "speed breaker",
                    "गड्ढा",
                    "सड़क",
                    "फुटपाथ",
                    "गुಂಡಿ",
                    "ರಸ್ತೆ",
                ]
            ):
                dept = "Roads and Infrastructure"
            else:
                dept = "Roads and Infrastructure"

            return schema.model_validate(
                {
                    "recommended_department": dept,
                    "secondary_departments": [],
                    "justification": f"Grievance falls under jurisdiction of {dept}.",
                    "confidence": confidence,
                }
            )

        # 3. Handle Priority Assessment
        if issubclass(schema, PriorityAssessmentResult):
            is_critical = any(
                k in p_lower
                for k in [
                    "live wire",
                    "sparking",
                    "collapse",
                    "electrocution",
                    "fatal",
                    "gas leak",
                    "sinkhole",
                    "bridge collapse",
                    "wall collapse",
                    "खुला तार",
                    "करंट",
                    "बिजली का झटका",
                    "आग",
                    "पुल गिर",
                    "दीवार गिर",
                    "गैस रिसाव",
                    "धंस गई",
                    "ತೆರೆದ ತಂತಿ",
                    "ವಿದ್ಯುತ್ ಆಘಾತ",
                    "ಬೆಂಕಿ",
                    "ಕುಸಿತ",
                    "ಅನಿಲ ಸೋರಿಕೆ",
                ]
            )
            is_high = any(
                k in p_lower
                for k in [
                    "burst",
                    "overflowing",
                    "contamination",
                    "severe",
                    "major",
                    "open manhole",
                    "uncovered manhole",
                    "toxic",
                    "खुला मैनहोल",
                    "ತೆರೆದ ಮ್ಯಾನ್‌ಹೋಲ್",
                    "ತೀವ್ರ",
                ]
            )
            is_low = any(
                k in p_lower
                for k in [
                    "low pressure",
                    "flicker",
                    "dim",
                    "minor",
                    "broken bench",
                    "overgrown grass",
                    "swing",
                    "tiles",
                    "paver",
                    "speed breaker",
                    "dry leaves",
                    "sweep",
                    "irregular",
                    "fountain",
                    "sprinkler",
                    "धीमी",
                    "सूखी घास",
                    "हल्का",
                    "कम दबाव",
                    "ಮಿಣುಕುತ್ತಿದೆ",
                    "ಒಣಗಿದ ಹುಲ್ಲು",
                    "ಕಡಿಮೆ ಒತ್ತಡ",
                    "ಪಾದಚಾರಿ ಮಾರ್ಗ ಅಗೆದಿದ್ದಾರೆ",
                    "ವಾರ ಕಳೆದಿದೆ",
                    "ಗುರುತು ಕಾಣುತ್ತಿಲ್ಲ",
                ]
            )

            if is_critical:
                priority = "CRITICAL"
                sla = 4
            elif is_high:
                priority = "HIGH"
                sla = 24
            elif is_low:
                priority = "LOW"
                sla = 168
            else:
                priority = "MEDIUM"
                sla = 48

            return schema.model_validate(
                {
                    "recommended_priority": priority,
                    "suggested_sla_hours": sla,
                    "hazard_indicators": {
                        "immediate_safety_hazard": is_critical or is_high,
                        "public_health_hazard": "contamination" in p_lower
                        or "जहरीला" in p_lower
                        or "ವಿಷಕಾರಿ" in p_lower,
                        "infrastructure_damage": True,
                        "vulnerable_population_impacted": False,
                    },
                    "rationale": f"Assessed as {priority} urgency based on public safety keywords.",
                    "confidence": confidence,
                }
            )

        # 4. Handle Grievance Interpretation
        if issubclass(schema, InterpretationResult):
            if is_vague or (is_adversarial and "wire" not in p_lower):
                cat = "General Municipal Services"
                sub = "General Maintenance"
                facts = ["Citizen filed municipal grievance"]
                causes = ["Unverified hypothesis: General municipal condition"]
            elif any(
                k in p_lower
                for k in [
                    "light",
                    "dark",
                    "pole",
                    "lamp",
                    "electricity",
                    "wire",
                    "transformer",
                    "sparking",
                    "flicker",
                    "बिजली",
                    "खंभा",
                    "तार",
                    "करंट",
                    "ಸ್ಪಾರ್ಕ್",
                    "ದೀಪ",
                    "ಕಂಬ",
                    "ವಿದ್ಯುತ್",
                    "ತಂತಿ",
                ]
            ):
                cat = "Electricity & Lighting"
                sub = "Streetlight Repair"
                facts = ["Streetlight fixture not functioning at night"]
                causes = ["Unverified hypothesis: Circuit breaker trip or burnt lamp fixture"]
            elif any(
                k in p_lower
                for k in [
                    "water",
                    "leak",
                    "pipe",
                    "pipeline",
                    "tap",
                    "meter",
                    "drinking",
                    "pressure",
                    "पानी",
                    "पाइप",
                    "नल",
                    "मीटर",
                    "ನೀರು",
                    "ನಲ್ಲಿ",
                ]
            ):
                cat = "Water Supply & Sewerage"
                sub = "Pipe Leakage"
                facts = ["Water pipeline actively leaking onto public road"]
                causes = ["Unverified hypothesis: High distribution pressure or joint failure"]
            elif any(
                k in p_lower
                for k in [
                    "garbage",
                    "trash",
                    "dump",
                    "waste",
                    "debris",
                    "dustbin",
                    "dead",
                    "carcass",
                    "कचरा",
                    "कूड़ा",
                    "मलबा",
                    "डस्टबिन",
                    "ಕಸ",
                    "ತ್ಯಾಜ್ಯ",
                ]
            ):
                cat = "Solid Waste Management"
                sub = "Garbage Pileup"
                facts = ["Uncollected waste accumulated in public space"]
                causes = ["Unverified hypothesis: Missed collection route cycle"]
            elif any(
                k in p_lower
                for k in [
                    "drain",
                    "gutter",
                    "flood",
                    "sewage",
                    "manhole",
                    "waterlogging",
                    "silt",
                    "नाली",
                    "सीवर",
                    "मैनहोल",
                    "जलभराव",
                    "कीचड़",
                    "ಚರಂಡಿ",
                    "ಮ್ಯಾನ್‌ಹೋಲ್",
                ]
            ):
                cat = "Stormwater & Drainage"
                sub = "Drain Blockage"
                facts = ["Stormwater drain blocked and overflowing"]
                causes = ["Unverified hypothesis: Silt and plastic debris obstruction"]
            elif any(
                k in p_lower
                for k in [
                    "park",
                    "tree",
                    "bench",
                    "swing",
                    "garden",
                    "lawn",
                    "branch",
                    "पार्क",
                    "पेड़",
                    "घास",
                    "झूला",
                    "ಉದ್ಯಾನ",
                    "ಮರ",
                    "ಹುಲ್ಲು",
                ]
            ):
                cat = "Parks & Recreation"
                sub = "Park Maintenance"
                facts = ["Park facility or tree requires municipal attention"]
                causes = ["Unverified hypothesis: Natural vegetation overgrowth"]
            elif any(
                k in p_lower
                for k in [
                    "pothole",
                    "crater",
                    "road",
                    "tar",
                    "asphalt",
                    "footpath",
                    "bridge",
                    "sinkhole",
                    "divider",
                    "median",
                    "speed breaker",
                    "गड्ढा",
                    "सड़क",
                    "फुटपाथ",
                    "पुल",
                    "गुಂಡಿ",
                    "ರಸ್ತೆ",
                    "ಫುಟ್‌ಪಾತ್",
                ]
            ):
                cat = "Roads & Footpaths"
                sub = "Pothole Repair"
                facts = ["Pothole observed in road surface", "Impacting vehicular traffic"]
                causes = ["Unverified hypothesis: Monsoon moisture infiltration and sub-base wear"]
            else:
                cat = "General Municipal Services"
                sub = "General Maintenance"
                facts = ["Citizen filed municipal grievance"]
                causes = ["Unverified hypothesis: General wear and tear"]

            return schema.model_validate(
                {
                    "category": cat,
                    "sub_category": sub,
                    "location_hints": ["Reported municipal location"],
                    "key_facts": facts,
                    "reported_facts": facts,
                    "inferences": ["Requires on-site municipal verification"],
                    "potential_root_causes": causes,
                    "officer_summary": f"Citizen grievance regarding {sub.lower()}. Physical inspection recommended.",
                    "confidence": confidence,
                }
            )

        raise NotImplementedError(
            f"MockProvider does not have a generator for schema {schema.__name__}"
        )

    async def embed_text(self, text: str) -> list[float]:
        """Generates a deterministic 768-dimensional mock embedding vector capturing semantic clusters."""
        vec = [0.0] * 768
        t_lower = text.lower()
        clusters = [
            (
                [
                    "pothole",
                    "crater",
                    "road",
                    "tar",
                    "asphalt",
                    "गड्ढा",
                    "गुಂಡಿ",
                    "koramangala",
                    "80ft",
                ],
                0,
                100,
            ),
            (
                [
                    "transformer",
                    "sparking",
                    "fire",
                    "wire",
                    "voltage",
                    "electric",
                    "इंदिरानगर",
                    "ಇಂದಿರಾನಗರ",
                ],
                100,
                200,
            ),
            (
                [
                    "pipe",
                    "leak",
                    "water",
                    "burst",
                    "drinking",
                    "whitefield",
                    "व्हाइटफील्ड",
                    "ವೈಟ್‌ಫೀಲ್ಡ್",
                ],
                200,
                300,
            ),
            (["garbage", "dump", "trash", "waste", "jayanagar", "जयनगर", "ಜಯನಗರ"], 300, 400),
            (["manhole", "uncovered", "storm", "drain", "mg road", "एमजी रोड", "ಎಂಜಿ ರೋಡ್"], 400, 500),
            (["tree", "branch", "banyan", "malleshwaram", "मल्लेश्वरम", "ಮಲ್ಲೇಶ್ವರಂ"], 500, 600),
            (["sinkhole", "frazer", "coles", "फ्रेजर", "ಫ್ರೇಜರ್"], 600, 700),
        ]
        for keywords, start, end in clusters:
            if any(k in t_lower for k in keywords):
                for idx in range(start, end):
                    vec[idx] = 1.0

        h = hashlib.sha256(text.encode("utf-8")).digest()
        for i in range(768):
            vec[i] += (h[i % len(h)] - 128) / 256.0
        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_text(t) for t in texts]


class GroqProvider(LLMProvider):
    """Llama 3.3-70B running on Groq LPU cloud — extremely low latency inference.

    Uses the OpenAI-compatible /chat/completions endpoint with native JSON mode.
    Embedding is NOT supported by Groq; GeminiProvider or MockProvider handles
    vector embeddings separately.
    """

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile") -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.groq.com/openai/v1"

    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"] or ""

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_instruction: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        schema_json = json.dumps(schema.model_json_schema())
        instruction = (
            f"{system_instruction}\n\n" if system_instruction else ""
        ) + f"You MUST return ONLY valid JSON conforming to this JSON Schema:\n{schema_json}"

        messages: list[dict[str, str]] = [
            {"role": "system", "content": instruction},
            {"role": "user", "content": prompt},
        ]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            # Native JSON mode — Groq guarantees the response is valid JSON.
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"] or "{}"

        parsed = json.loads(raw_text)
        return schema.model_validate(parsed)


class GeminiProvider(LLMProvider, EmbeddingProvider):
    """Google Gemini LLM and Embedding provider via HTTP REST API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
        embedding_model: str = "text-embedding-004",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.embedding_model = embedding_model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    async def generate_text(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature},
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError("No candidate responses returned by Gemini API")
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                raise ValueError("Empty candidate content parts returned by Gemini API")
            return str(parts[0].get("text", ""))

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_instruction: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        schema_json = json.dumps(schema.model_json_schema())
        instruction = (
            f"{system_instruction}\n\n" if system_instruction else ""
        ) + f"You MUST return ONLY valid JSON conforming to this JSON Schema:\n{schema_json}"

        raw_text = await self.generate_text(
            prompt=prompt,
            system_instruction=instruction,
            temperature=temperature,
        )

        clean_json = raw_text.strip()
        if clean_json.startswith("```"):
            lines = clean_json.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_json = "\n".join(lines).strip()

        data = json.loads(clean_json)
        return schema.model_validate(data)

    async def embed_text(self, text: str) -> list[float]:
        url = f"{self.base_url}/models/{self.embedding_model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.embedding_model}",
            "content": {"parts": [{"text": text}]},
        }
        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("embedding", {})
            return [float(v) for v in embedding.get("values", [])]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # In Gemini v1beta batchEmbedContents is available
        return [await self.embed_text(t) for t in texts]


# Provider singleton instances
_mock_provider = MockProvider()


def get_llm_provider() -> LLMProvider:
    """Return the active LLM provider based on the AI_PROVIDER setting.

    Priority order:
      1. groq  — Llama 3.3-70B on Groq LPU cloud (fast, free tier)
      2. gemini — Google Gemini (kept as automatic fallback)
      3. mock  — deterministic keyword-based provider for tests / offline
    """
    provider = settings.AI_PROVIDER.lower().strip()

    if provider == "groq":
        if not settings.GROQ_API_KEY:
            logger.warning(
                "AI_PROVIDER=groq but GROQ_API_KEY is not set. "
                "Falling back to Gemini or mock provider."
            )
        else:
            return GroqProvider(
                api_key=settings.GROQ_API_KEY,
                model=settings.GROQ_MODEL,
            )

    # Fallback: Gemini (also used when provider='gemini')
    if settings.GEMINI_API_KEY:
        return GeminiProvider(
            api_key=settings.GEMINI_API_KEY,
            model=settings.GEMINI_MODEL,
            embedding_model=settings.GEMINI_EMBEDDING_MODEL,
        )

    logger.warning("No AI API key configured. Using MockProvider.")
    return _mock_provider


def get_embedding_provider() -> EmbeddingProvider:
    """Embeddings always use GeminiProvider (Groq does not support embeddings)."""
    if settings.GEMINI_API_KEY:
        return GeminiProvider(
            api_key=settings.GEMINI_API_KEY,
            model=settings.GEMINI_MODEL,
            embedding_model=settings.GEMINI_EMBEDDING_MODEL,
        )
    return _mock_provider


def get_mock_provider() -> MockProvider:
    return _mock_provider
