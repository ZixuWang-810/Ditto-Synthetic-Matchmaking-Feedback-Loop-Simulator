"""Batch persona generation using LLM structured output (Ollama local models)."""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src import config
from src.llm.client import get_llm_client, LLMClient
from src.models.persona import (
    Persona,
    Gender,
    DateType,
    DegreeLevel,
    CommunicationStyle,
    PreferenceStrictness,
    DatingPreferences,
)

logger = logging.getLogger(__name__)


# ── Diversity Distribution Targets ────────────────────────────────────────────
GENDER_DISTRIBUTION = {Gender.MALE: 0.45, Gender.FEMALE: 0.45, Gender.NON_BINARY: 0.10}
DATE_TYPE_DISTRIBUTION = {
    DateType.LIFE_PARTNER: 0.15,
    DateType.SERIOUS_RELATIONSHIP: 0.35,
    DateType.CASUAL_DATES: 0.35,
    DateType.NEW_FRIENDS: 0.15,
}
ETHNICITY_POOL = [
    "White", "Black", "Hispanic/Latino", "East Asian", "South Asian",
    "Southeast Asian", "Middle Eastern", "Mixed/Multiracial", "Pacific Islander",
]

CALIFORNIA_UNIVERSITIES = [
    # UC System
    "UC Berkeley", "UCLA", "UC San Diego", "UC Davis",
    "UC Santa Barbara", "UC Irvine", "UC Santa Cruz",
    "UC Riverside", "UC Merced",
    # CSU System
    "Cal Poly San Luis Obispo", "San Diego State University",
    "Cal State Long Beach", "Cal State Fullerton",
    "San Jose State University", "Cal State Northridge",
    "Sacramento State", "Fresno State", "Cal Poly Pomona",
    "Cal State LA", "Chico State", "Sonoma State", "Humboldt State",
]


class PersonaGenerator:
    """Generates realistic college student dating personas with diversity controls.
    
    Uses Ollama local models. Generates one persona at a time for reliability,
    since local models are less reliable at generating large, complex JSON batches.
    """

    def __init__(self, llm_client: LLMClient | None = None):
        self.client = llm_client or get_llm_client()

    def generate(
        self,
        count: int = config.DEFAULT_PERSONA_COUNT,
        batch_size: int = config.PERSONA_BATCH_SIZE,
        output_path: Path | None = None,
        mongo_enabled: bool = False,
    ) -> list[Persona]:
        """Generate personas one at a time for maximum reliability.

        Args:
            count: Total number of personas to generate.
            batch_size: Ignored for Ollama (kept for API compat). Generates one at a time.
            output_path: Path to write JSONL output.
            mongo_enabled: If True, also sync personas to MongoDB.

        Returns:
            List of generated Persona objects (only the newly generated ones).
        """
        output_path = output_path or (config.PERSONAS_DIR / "persona_pool.jsonl")
        
        all_personas: list[Persona] = []
        if output_path.exists():
            all_personas = self.load_personas(output_path)
            logger.info(f"Loaded {len(all_personas)} existing personas. Enhancing pool with {count} more...")
        else:
            logger.info(f"Generating {count} personas (one at a time for local model reliability)...")

        new_personas: list[Persona] = []

        for i in range(count):
            diversity_hints = self._compute_diversity_hints(all_personas, len(all_personas) + count)
            existing_names = {p.name for p in all_personas}
            retries = 0
            max_retries = 5

            while retries < max_retries:
                try:
                    persona = self._generate_single_persona(
                        persona_num=i + 1,
                        total=count,
                        diversity_hints=diversity_hints,
                        existing_names=existing_names,
                    )
                    all_personas.append(persona)
                    new_personas.append(persona)
                    logger.info(
                        f"  [{i+1}/{count}] Generated: {persona.name} "
                        f"({persona.gender.value}, {persona.ethnicity}, {persona.date_type.value})"
                    )
                    break
                except Exception as e:
                    retries += 1
                    logger.warning(f"  [{i+1}/{count}] Attempt {retries} failed: {e}")
                    if retries >= max_retries:
                        logger.error(f"  [{i+1}/{count}] Skipping after {max_retries} failures")

        # Append to JSONL
        self._write_jsonl(new_personas, output_path, mode="a")
        logger.info(f"Appended {len(new_personas)} new personas to {output_path} (Total pool size: {len(all_personas)})")

        # Sync to MongoDB if enabled
        if mongo_enabled and new_personas:
            try:
                from src.storage.mongo_client import get_mongo_storage
                mongo = get_mongo_storage()
                inserted = mongo.insert_personas(new_personas)
                logger.info(f"Synced {inserted} personas to MongoDB")
            except Exception as e:
                logger.warning(f"MongoDB sync failed (JSONL still saved): {e}")

        return new_personas

    def _generate_single_persona(
        self,
        persona_num: int,
        total: int,
        diversity_hints: str,
        existing_names: set[str],
    ) -> Persona:
        """Generate a single persona via Ollama JSON mode."""

        prompt = f"""Generate exactly 1 unique, realistic college student dating profile as JSON.

This is persona #{persona_num} out of {total}.

DIVERSITY REQUIREMENTS:
{diversity_hints}

SCHEMA — Your JSON response MUST have ALL of these fields:
{{
  "name": "Full Name",
  "age": 20,
  "gender": "male|female|non_binary",
  "ethnicity": "e.g. East Asian, White, Hispanic/Latino, Black, South Asian",
  "height_inches": 67,
  "hobbies": ["hobby1", "hobby2", "hobby3"],
  "degree_level": "freshman|sophomore|junior|senior|masters|phd",
  "date_type": "life_partner|serious_relationship|casual_dates|new_friends",
  "dating_preferences": {{
    "preferred_genders": ["male"],
    "preferred_ethnicities": [],
    "preferred_age_min": 18,
    "preferred_age_max": 25,
    "physical_attraction_criteria": ["tall", "athletic"],
  }},
  "communication_style": "direct|enthusiastic|sarcastic|reserved|flirty",
  "preference_strictness": "strict|moderate|open",
  "bio": "A casual, authentic bio written as a real college student would"
}}

RULES:
- Name must NOT be any of: {', '.join(list(existing_names)[:20]) if existing_names else 'none yet'}
- Age between 18-30, most commonly 19-26.
- Use at least 2 hobbies (3-5 preferred). Be creative and specific — not everyone likes hiking.
- Bio should sound like a real college student — casual, authentic, maybe funny.

Generate the JSON for 1 persona now."""

        system_prompt = (
            "You are a data generator that creates realistic, diverse synthetic "
            "college student dating profiles. Output ONLY valid JSON matching the exact "
            "schema requested. Do not add extra fields or commentary."
        )

        # Use Ollama JSON mode
        client = self.client._get_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        response = client.chat(
            model=self.client.model,
            messages=messages,
            format="json",
            options={"temperature": 0.9},
        )

        raw_json = response["message"]["content"]
        data = json.loads(raw_json)

        # Handle case where model wraps in a key like {"persona": {...}} or {"personas": [...]}
        if "persona" in data and isinstance(data["persona"], dict):
            data = data["persona"]
        elif "personas" in data and isinstance(data["personas"], list):
            data = data["personas"][0]

        # Sanitize common LLM output quirks before validation
        data = self._sanitize_data(data)

        # Assign a random California university
        persona = Persona.model_validate(data)
        persona.university = random.choice(CALIFORNIA_UNIVERSITIES)

        # Validate and return
        return persona

    @staticmethod
    def _sanitize_data(data: dict) -> dict:
        """Fix common LLM output quirks before Pydantic validation.
        
        Local models often produce slightly wrong enum values (e.g. non-binary
        instead of non_binary) or exceed field length limits.
        """
        # Normalize enum-like string fields: replace hyphens with underscores
        enum_fields = ["gender", "date_type", "degree_level", "communication_style", "preference_strictness"]
        for field in enum_fields:
            if field in data and isinstance(data[field], str):
                data[field] = data[field].replace("-", "_").replace(" ", "_").lower()

        # Fix preferred_genders in dating_preferences
        if "dating_preferences" in data and isinstance(data["dating_preferences"], dict):
            prefs = data["dating_preferences"]
            if "preferred_genders" in prefs and isinstance(prefs["preferred_genders"], list):
                prefs["preferred_genders"] = [
                    g.replace("-", "_").replace(" ", "_").lower()
                    for g in prefs["preferred_genders"]
                ]

        # Truncate bio if too long (local models can be verbose)
        if "bio" in data and isinstance(data["bio"], str) and len(data["bio"]) > 500:
            data["bio"] = data["bio"][:497] + "..."

        # Clamp age
        if "age" in data and isinstance(data["age"], (int, float)):
            data["age"] = max(18, min(30, int(data["age"])))

        # Clamp height
        if "height_inches" in data and isinstance(data["height_inches"], (int, float)):
            data["height_inches"] = max(55, min(84, int(data["height_inches"])))

        # Ensure hobbies has at least 2 items
        if "hobbies" in data and isinstance(data["hobbies"], list):
            if len(data["hobbies"]) < 2:
                data["hobbies"].extend(["exploring campus", "watching movies"][:2 - len(data["hobbies"])])

        # Provide defaults for fields the LLM might skip
        data.setdefault("bio", "Just a college student looking for good vibes.")
        data.setdefault("communication_style", "direct")
        data.setdefault("preference_strictness", "moderate")
        data.setdefault("dating_preferences", {
            "preferred_genders": ["female"],
            "preferred_age_min": 18,
            "preferred_age_max": 25,
        })

        return data

    def _compute_diversity_hints(
        self, existing: list[Persona], target_total: int
    ) -> str:
        """Compute what diversity gaps need filling."""
        if not existing:
            return (
                "Create a diverse first persona. Vary genders, ethnicities, "
                "date types, degree levels, and communication styles across the batch."
            )

        # Count distributions
        gender_counts = {g: 0 for g in Gender}
        date_type_counts = {d: 0 for d in DateType}
        ethnicity_counts: dict[str, int] = {}

        for p in existing:
            gender_counts[p.gender] += 1
            date_type_counts[p.date_type] += 1
            ethnicity_counts[p.ethnicity] = ethnicity_counts.get(p.ethnicity, 0) + 1

        n = len(existing)
        hints = []

        # Gender balance hints
        for gender, target_pct in GENDER_DISTRIBUTION.items():
            current_pct = gender_counts[gender] / n
            if current_pct < target_pct - 0.05:
                hints.append(f"- Include a {gender.value} persona (currently {current_pct:.0%}, target ~{target_pct:.0%})")

        # Date type balance
        for dt, target_pct in DATE_TYPE_DISTRIBUTION.items():
            current_pct = date_type_counts[dt] / n
            if current_pct < target_pct - 0.05:
                hints.append(f"- Use {dt.value} as date type (currently {current_pct:.0%}, target ~{target_pct:.0%})")

        # Ethnicity coverage
        missing = [e for e in ETHNICITY_POOL if e not in ethnicity_counts]
        if missing:
            hints.append(f"- Use one of these under-represented ethnicities: {', '.join(missing[:3])}")

        return "\n".join(hints) if hints else "Current diversity is good. Maintain variety."

    def _write_jsonl(self, personas: list[Persona], path: Path, mode: str = "w"):
        """Write personas to a JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, mode, encoding="utf-8") as f:
            for persona in personas:
                f.write(persona.model_dump_json() + "\n")

    @staticmethod
    def load_personas(path: Path | None = None) -> list[Persona]:
        """Load personas from a JSONL file."""
        path = path or (config.PERSONAS_DIR / "persona_pool.jsonl")
        personas = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    personas.append(Persona.model_validate_json(line))
        logger.info(f"Loaded {len(personas)} personas from {path}")
        return personas
