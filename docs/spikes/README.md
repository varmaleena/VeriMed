# Spike evidence

Store sanitized measurements here. Exclude access tokens, generated clinical content, and account identifiers. No live spike evidence has been collected.

| Spike | Local deliverable                  | Execution status                                                                                                                                 |
| ----- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| S1    | ADR 001                            | Runtime and Gateway spike pending                                                                                                                |
| S2    | ADR 002                            | Proxy and Guardrails spike pending                                                                                                               |
| S3    | `spikes/s3_healthscribe_submit.py` | Submission code only. Provision the encrypted sandbox, collect output field counts and evidence references, then delete the job and its objects. |
| S4    | `spikes/s4_hapi_import.py`         | Local HAPI timing script. Synthea generation, HealthLake leg, and comparison pending.                                                            |
| S5    | `spikes/s5_bedrock_inventory.py`   | AWS catalog listing script. Regional results and alias selection pending.                                                                        |
