"""Dynamic Configuration Loader.

Loads taxonomy, routing, detector registry, and pipeline configuration
from editable YAML/JSON files without hardcoded values.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


class ConfigLoader:
    _instance: Optional["ConfigLoader"] = None

    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = Path(config_dir or os.getenv("CONFIG_DIR", "config")).resolve()
        self._taxonomy: Dict[str, Any] = {}
        self._routing: Dict[str, Any] = {}
        self._detectors: Dict[str, Any] = {}
        self._pipeline: Dict[str, Any] = {}
        self.reload()

    @classmethod
    def get_instance(cls) -> "ConfigLoader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def reload(self) -> None:
        """Reload all configuration files from disk."""
        tax_path = self.config_dir / "taxonomy.yaml"
        if tax_path.exists():
            with open(tax_path, "r", encoding="utf-8") as f:
                self._taxonomy = yaml.safe_load(f) or {}

        routing_path = self.config_dir / "routing.yaml"
        if routing_path.exists():
            with open(routing_path, "r", encoding="utf-8") as f:
                self._routing = yaml.safe_load(f) or {}

        det_path = self.config_dir / "detector_registry.yaml"
        if det_path.exists():
            with open(det_path, "r", encoding="utf-8") as f:
                self._detectors = yaml.safe_load(f) or {}

        pipe_path = self.config_dir / "pipeline.yaml"
        if pipe_path.exists():
            with open(pipe_path, "r", encoding="utf-8") as f:
                self._pipeline = yaml.safe_load(f) or {}

    @property
    def taxonomy(self) -> Dict[str, Any]:
        return self._taxonomy.get("taxonomy", {})

    @property
    def taxonomy_metadata(self) -> Dict[str, Any]:
        return {
            "version": self._taxonomy.get("version", "2.1.0"),
            "default_class": self._taxonomy.get("default_class", "unknown"),
            "ambiguity_margin": self._taxonomy.get("ambiguity_margin", 0.15),
            "minimum_confidence": self._taxonomy.get("minimum_confidence", 0.50),
        }

    @property
    def routing_table(self) -> Dict[str, Any]:
        return self._routing.get("routing_destinations", {})

    @property
    def routing_metadata(self) -> Dict[str, Any]:
        return {
            "version": self._routing.get("version", "2.1.0"),
            "default_review_queue": self._routing.get("default_review_queue", "MANUAL_HUMAN_REVIEW_QUEUE"),
        }

    @property
    def detectors(self) -> Dict[str, Any]:
        return self._detectors.get("detectors", {})

    @property
    def pipeline_config(self) -> Dict[str, Any]:
        return self._pipeline

    @property
    def structure_types(self) -> list:
        return self._pipeline.get("structures", {}).get("types", [])

    @property
    def structure_type_map(self) -> Dict[str, Dict[str, Any]]:
        return {st["id"]: st for st in self.structure_types if "id" in st}
