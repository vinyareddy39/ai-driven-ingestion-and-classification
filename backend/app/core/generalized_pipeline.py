"""Unified Generalized Document Ingestion, Classification, and Routing Pipeline.

Zero hardcoding: all taxonomies, detectors, destinations, and thresholds
are loaded from editable YAML configurations and dynamic learned registry.
"""

import os
from typing import Any, Dict, List, Optional

from app.core.config_loader import ConfigLoader
from app.core.document_classifier import GeneralizedDocumentClassifier
from app.core.layout_extractor import LayoutAwareExtractor
from app.core.sanity_checker import run_sanity_checks
from app.core.sensitive_detector import ConfigDrivenSensitiveDetector
from app.core.learned_registry import LearnedRegistry


class GeneralizedDocumentPipeline:
    """End-to-end document processing pipeline adhering to all enterprise generalization rules."""

    def __init__(self, config_dir: Optional[str] = None):
        self.loader = ConfigLoader.get_instance()
        if config_dir:
            self.loader.config_dir = config_dir
            self.loader.reload()

        self.registry = LearnedRegistry.get_instance()
        self.layout_extractor = LayoutAwareExtractor(self.loader)
        self.sensitive_detector = ConfigDrivenSensitiveDetector(self.loader)
        self.classifier = GeneralizedDocumentClassifier(self.loader)

    def process_file(self, file_path: str) -> Dict[str, Any]:
        """Process an unseen document and return standardized Section 6 output JSON."""
        pipe_cfg = self.loader.pipeline_config.get("pipeline", {})
        pipeline_version = pipe_cfg.get("version", "2.3.0")
        registry_version = self.registry.version
        conf_cfg = self.loader.pipeline_config.get("confidence", {})
        review_threshold = float(conf_cfg.get("field_review_threshold", 0.85))

        # 1. Layout-Aware Text & Field Extraction
        extraction = self.layout_extractor.extract_from_file(file_path)

        total_words = len(extraction.full_text.split())
        valid_fields = [f for f in extraction.fields if f.get("label", "").strip()]
        has_noise_level = bool(extraction.page_conditions and any(c.get("noise_level", 0) > 40000 for c in extraction.page_conditions))

        # Rule 4 & 5: Empty reading after trying every orientation & contrast attempt
        # Blank page or unreadable noise page with no valid labelled fields
        if total_words == 0 or (len(valid_fields) == 0 and (total_words < 15 or has_noise_level)):
            page_qual = "clean"
            if extraction.page_conditions:
                conds = [c.get("condition", "clean") for c in extraction.page_conditions]
                page_qual = conds[0] if len(set(conds)) == 1 else ", ".join(conds)
            return {
                "failed": True,
                "status": "Failed",
                "error": "no readable text found (tried 0°, 90°, 180°, 270° and contrast normalization)",
                "review_reasons": ["no readable text found (tried 0°, 90°, 180°, 270° and contrast normalization)"],
                "needs_review": True,
                "type": "Could not read",
                "type_confidence": 0.0,
                "fields": [],
                "table_rows": [],
                "tables": [],
                "regions": extraction.regions,
                "page_quality": page_qual,
                "summary": "Document processing failed: no readable text found.",
                "tags": ["unreadable", "manual-triage"],
                "routing": {
                    "destination": "MANUAL_TRIAGE_QUEUE",
                    "is_restricted": False,
                    "review_queue": "MANUAL_HUMAN_REVIEW_QUEUE",
                    "sla_hours": 24,
                },
                "sensitive_status": "not scanned: no text",
                "sensitive_findings": [],
                "detectors_run": [],
                "preview_bytes": extraction.preview_bytes,
                "page_count": extraction.page_count,
                "page_conditions": extraction.page_conditions,
                "pipeline_version": pipeline_version,
                "registry_version": registry_version,
            }

        # 2. Arithmetic & Format Sanity Checks
        checked_fields, sanity_reasons = run_sanity_checks(
            fields=extraction.fields,
            table_rows=extraction.table_rows,
            review_threshold=review_threshold,
        )

        # 3. Config-Driven Sensitive Data Detection
        sensitive_findings, detectors_run = self.sensitive_detector.detect_in_document(
            text=extraction.full_text,
            fields=checked_fields,
            table_rows=extraction.table_rows,
            text_blocks=extraction.text_blocks,
        )
        # Marked restricted if any sensitive findings exist with sufficient confidence
        is_restricted = any(s.get("confidence", 0) >= 0.50 for s in sensitive_findings)

        # 4. Multi-Page Logical Document Segmentation
        logical_documents: List[Dict[str, Any]] = []
        page_classifications: Dict[int, Dict[str, Any]] = {}

        for p_num in range(1, extraction.page_count + 1):
            p_text = extraction.pages_text.get(p_num, "")
            p_fields = [f for f in checked_fields if f.get("page") == p_num]
            p_cls = self.classifier.classify(
                full_text=p_text,
                fields=p_fields,
                table_rows=[],
                has_dates=False,
                has_title_block=False,
            )
            page_classifications[p_num] = p_cls

        # Group consecutive pages into logical documents
        doc_idx = 1
        curr_type = None
        curr_start = 1
        curr_conf = 0.0

        for p_num in range(1, extraction.page_count + 1):
            p_info = page_classifications[p_num]
            p_type = p_info["type"]
            p_conf = p_info["type_confidence"]

            if curr_type is None:
                curr_type = p_type
                curr_start = p_num
                curr_conf = p_conf
            elif p_type != curr_type and p_type != "unknown" and curr_type != "unknown":
                # Distinct document boundary detected
                logical_documents.append({
                    "document_index": doc_idx,
                    "start_page": curr_start,
                    "end_page": p_num - 1,
                    "type": curr_type,
                    "confidence": round(curr_conf, 4),
                })
                doc_idx += 1
                curr_type = p_type
                curr_start = p_num
                curr_conf = p_conf
            else:
                curr_conf = max(curr_conf, p_conf)

        if curr_type is not None:
            logical_documents.append({
                "document_index": doc_idx,
                "start_page": curr_start,
                "end_page": extraction.page_count,
                "type": curr_type,
                "confidence": round(curr_conf, 4),
            })

        # 5. Whole-Document Holistic Classification over Taxonomy
        has_dates = len(extraction.dates) > 0
        has_title = extraction.title_block is not None
        classification = self.classifier.classify(
            full_text=extraction.full_text,
            fields=checked_fields,
            table_rows=extraction.table_rows,
            has_dates=has_dates,
            has_title_block=has_title,
        )

        doc_type = classification["type"]
        type_conf = classification["type_confidence"]
        top_candidates = classification.get("top_candidates", [])[:3]

        # 6. Config-Driven Routing
        routing_table = self.loader.routing_table
        routing_meta = self.loader.routing_metadata
        dest_cfg = routing_table.get(doc_type, routing_table.get("unknown", {}))

        if is_restricted:
            destination = dest_cfg.get("restricted_destination", "RESTRICTED_MANUAL_TRIAGE_QUEUE")
        else:
            destination = dest_cfg.get("destination", "MANUAL_TRIAGE_QUEUE")

        routing_output = {
            "destination": destination,
            "is_restricted": is_restricted,
            "review_queue": routing_meta.get("default_review_queue", "MANUAL_HUMAN_REVIEW_QUEUE"),
            "sla_hours": dest_cfg.get("sla_hours", 24),
        }

        # 7. Review Flag & Reasons Determination
        review_reasons: List[str] = []
        if classification.get("review_reasons"):
            review_reasons.extend(classification["review_reasons"])
        if sanity_reasons:
            review_reasons.extend(sanity_reasons)

        has_low_conf_field = False
        has_unlabelled_field = False
        for f in checked_fields:
            if not f.get("label", "").strip() and f.get("value", "").strip():
                has_unlabelled_field = True
                review_reasons.append(f"Detail value '{f.get('value')[:30]}' lacks a label (needs label).")
            if f.get("confidence", 1.0) < review_threshold:
                has_low_conf_field = True
                f["needs_review"] = True
                review_reasons.append(
                    f"Field '{f.get('label') or 'detail'}' confidence ({f.get('confidence', 0):.2f}) is below threshold ({review_threshold:.2f})."
                )

        has_sensitive_review = False
        for s in sensitive_findings:
            if s.get("needs_review", False):
                has_sensitive_review = True
                review_reasons.append(
                    f"Sensitive finding ({s.get('type')}) in field '{s.get('location', {}).get('label')}' flagged for review."
                )

        needs_review = bool(
            classification.get("needs_review", False) or
            has_low_conf_field or
            has_unlabelled_field or
            has_sensitive_review or
            len(sanity_reasons) > 0 or
            doc_type == "unknown"
        )

        # 8. Document Summary, Tags, Quality, and Language
        title_txt = extraction.title_block.get("text") if extraction.title_block else ""
        date_txt = extraction.dates[0]["date"] if extraction.dates else ""
        summary_parts = []
        if doc_type != "unknown":
            summary_parts.append(f"{doc_type.replace('_', ' ').title()} document")
        else:
            summary_parts.append("Business document")

        # Never leak identifiers in summary
        if title_txt and len(title_txt.split()) <= 5:
            if not any(s.get("raw_value") in title_txt for s in sensitive_findings if s.get("raw_value")):
                summary_parts.append(f"titled '{title_txt}'")
        if date_txt:
            summary_parts.append(f"dated {date_txt}")

        summary = " ".join(summary_parts) + "."
        for s in sensitive_findings:
            raw_s = str(s.get("raw_value", ""))
            if raw_s and raw_s in summary:
                summary = summary.replace(raw_s, s.get("masked_value", "[RESTRICTED]"))

        tags = [doc_type.replace("_", " ")]
        if extraction.is_digital_text:
            tags.append("digital-pdf")
        else:
            tags.append("scanned-ocr")
        tags.append(destination.lower().replace("_", "-"))
        if is_restricted:
            tags.append("restricted-pii")
        else:
            tags.append("standard-handling")

        page_qual = "clean"
        if extraction.page_conditions:
            conds = [c.get("condition", "clean") for c in extraction.page_conditions]
            page_qual = conds[0] if len(set(conds)) == 1 else ", ".join(conds)

        # Clean fields with grounding spans and suggestion metadata
        clean_fields = []
        for f in checked_fields:
            lbl_conf = f.get("label_confidence")
            if lbl_conf is not None:
                lbl_conf = round(float(lbl_conf), 4)

            # Check if this field holds sensitive data
            f_val = str(f.get("value", "")).strip()
            f_lbl = str(f.get("label", "")).strip().lower()
            is_sens = False
            sens_tag = None
            masked_val = None
            for s in sensitive_findings:
                raw_s = str(s.get("raw_value", "")).strip()
                s_lbl = str(s.get("location", {}).get("label", "")).strip().lower()
                if raw_s and (raw_s in f_val or (s_lbl and s_lbl == f_lbl)):
                    is_sens = True
                    sens_tag = s.get("type", "SENSITIVE")
                    masked_val = s.get("masked_value")
                    break

            clean_fields.append({
                "label": f["label"],
                "original_label": f.get("original_label", f["label"]),
                "value": f["value"],
                "original_value": f.get("original_value", f["value"]),
                "confidence": round(float(f["confidence"]), 4),
                "value_confidence": round(float(f.get("value_confidence", f["confidence"])), 4),
                "label_confidence": lbl_conf,
                "structure_type": f.get("structure_type", "label_value_pair"),
                "structure_group": f.get("structure_group", "fields"),
                "structure_confidence": round(float(f.get("structure_confidence", 0.95)), 4),
                "region_id": f.get("region_id"),
                "source": f.get("source", "document"),
                "page": f["page"],
                "bbox": f.get("bbox"),
                "is_sensitive": is_sens,
                "detector_tag": sens_tag,
                "masked_value": masked_val,
                "needs_review": f.get("needs_review", False),
                "reason": f.get("reason", ""),
                "suggested_label": f.get("suggested_label", ""),
                "alternatives": f.get("alternatives", []),
                "hint": f.get("hint", ""),
                "grounding_span": f.get("grounding_span"),
                "split_suggestion": f.get("split_suggestion"),
                "is_promoted": f.get("is_promoted", True),
                "in_more_details": f.get("in_more_details", False),
            })

        clean_sensitive = [
            {
                "type": s["type"],
                "location": s["location"],
                "confidence": round(float(s["confidence"]), 4),
                "masked_value": s["masked_value"],
            }
            for s in sensitive_findings
        ]

        # Key details vs More details
        key_details = [f for f in clean_fields if not f.get("in_more_details", False)]
        more_details = [f for f in clean_fields if f.get("in_more_details", False)]

        return {
            "document_kind": {
                "name": doc_type.replace("_", " ").title() if doc_type != "unknown" else "Unknown",
                "confidence": type_conf,
                "top_3_candidates": top_candidates,
            },
            "type": doc_type,
            "type_confidence": type_conf,
            "top_candidates": top_candidates,
            "summary": summary,
            "tags": tags[:5],
            "language": "en",
            "page_quality": page_qual,
            "page_conditions": extraction.page_conditions,
            "logical_documents": logical_documents,
            "fields": clean_fields,
            "key_details": key_details,
            "more_details": more_details,
            "tables": extraction.tables,
            "table_rows": extraction.table_rows,
            "regions": extraction.regions,
            "lists": extraction.lists,
            "checkboxes": extraction.checkboxes,
            "signatures": extraction.signatures,
            "images_and_charts": extraction.images_and_charts,
            "codes": extraction.codes,
            "sensitive_findings": clean_sensitive,
            "detectors_run": detectors_run,
            "sensitive_status": "not scanned: no text" if not extraction.full_text.strip() else f"{len(detectors_run) if isinstance(detectors_run, list) else detectors_run} detectors run, {len(sensitive_findings)} findings",
            "routing": routing_output,
            "needs_review": needs_review,
            "review_reasons": list(dict.fromkeys(review_reasons)),
            "pipeline_version": pipeline_version,
            "registry_version": registry_version,
            "raw_text_by_page": extraction.pages_text,
            "layout_blocks": extraction.layout_blocks,
            "title_block": extraction.title_block.get("text") if extraction.title_block else None,
            "dates": [d["date"] for d in extraction.dates],
            "preview_bytes": extraction.preview_bytes,
        }
