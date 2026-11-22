"""Compatibility edits for the immutable Synthea v4 source security candidate."""

import subprocess
import sys
from pathlib import Path

COMMIT = "0185c09ea9d10a822c6f5f3ef9bdcbcbe960c813"


def patch(root: Path) -> None:
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if actual != COMMIT:
        raise ValueError("Only the reviewed immutable upstream source is supported")
    source = root / "src/main/java/org/mitre/synthea"
    edits = {
        "export/flexporter/CustomFHIRPathResourceGeneratorR4.java": {
            "org.hl7.fhir.r4.model.ExpressionNode": "org.hl7.fhir.r4.fhirpath.ExpressionNode",
            "org.hl7.fhir.r4.utils.FHIRPathEngine": "org.hl7.fhir.r4.fhirpath.FHIRPathEngine",
        },
        "helpers/PhysiologyValueGenerator.java": {
            "new Constructor(PhysiologyGeneratorConfig.class)": "new Constructor(PhysiologyGeneratorConfig.class, new org.yaml.snakeyaml.LoaderOptions())",
        },
        "engine/PhysiologySimulator.java": {
            "new Constructor(SimConfig.class)": "new Constructor(SimConfig.class, new org.yaml.snakeyaml.LoaderOptions())",
        },
        "export/flexporter/Mapping.java": {
            "new Constructor(Mapping.class)": "new Constructor(Mapping.class, new org.yaml.snakeyaml.LoaderOptions())",
        },
    }
    for relative, replacements in edits.items():
        path = source / relative
        text = path.read_text(encoding="utf-8")
        for old, new in replacements.items():
            if old not in text:
                raise ValueError("Upstream source differs from the reviewed patch")
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch(Path(sys.argv[1]))
