# Implementation status

The owner requested ordered implementation of all phases on November 19, with owner testing deferred
until the end. Automated verification continues for every slice. UI polish remains deferred.
A phase is not marked complete merely because its code exists; deployment and acceptance gaps stay explicit.

| Phase | Current state                                                                                      | Remaining acceptance work                                                                                        |
| ----- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 0     | Foundations/spikes implemented; dev foundation deployed                                            | Hosted CI/remote, organization accounts, outstanding FHIR benchmark                                              |
| 1     | In progress: auth, real Patients/Worklist, ledger, CKS client/cache/private API/no-NAT runtime IaC | Hub account/live PrivateLink/cache, mirror/quotas, full cell schema and hosting/observability/FHIR import checks |
| 2     | Not started                                                                                        | Real ingestion, simulator, transcript/draft storage and read-only workspace                                      |
| 3     | Not started                                                                                        | AgentCore audit graph, grounding/numeric checks and streamed findings                                            |
| 4     | Not started                                                                                        | Clinical safety, resolutions, gated sign-off and FHIR/ledger receipts                                            |
| 5     | Not started                                                                                        | MSP provisioning/fleet/metering and second cell                                                                  |
| 6     | Not started                                                                                        | Measured evaluation, load/chaos/security/accessibility and runbooks                                              |
| 7     | Not started                                                                                        | UI polish, HLD, demo/submission package and final owner testing                                                  |

Account topology remains separate management/hub/cell accounts. Only the standalone dev-cell profile
exists. Choosing the enterprise design does not supply credentials or an unused AWS account contact.
See BLOCKERS.md for prerequisites. Do not create accounts using the Cognito invitation address implicitly.
