# Dev budget

On November 18, 2026, the owner's AWS Billing screenshot showed the following totals.

| Billing field                    |    USD |
| -------------------------------- | -----: |
| Total available credit           | 365.60 |
| Total estimated amount remaining | 360.58 |
| Total amount used                |  14.40 |
| Total estimated amount used      |  19.42 |

Use the estimated remaining balance of $360.58 for planning. Do not subtract the estimated used amount again.
The Free Tier account-plan API separately returned $165.04. That plan-specific figure does not represent the full balance shown in Billing.
The screenshot says estimated amounts update approximately every 24 hours. Credit expiry and per-service eligibility need the individual credit details.

The owner approved a two-day HealthLake testing window, followed by recreation for recording.
At $0.27 per datastore-hour, 48 hours is approximately $12.96, excluding queries and supporting services.
The approved demo stack must include scheduled teardown and expose its expiry time.

For comparison, 22 continuous days of HealthLake would cost about $142.56. The existing nine single-AZ interface endpoints add approximately $47.52 over the same period at $0.01 per endpoint-hour. Together that is $190.08, leaving $170.50 from the reported balance before Aurora, speech, models, storage, KMS, logs, and other charges.

[HealthLake pricing](https://aws.amazon.com/healthlake/pricing/) · [PrivateLink pricing](https://aws.amazon.com/privatelink/pricing/)

The ledger foundation adds two retained KMS keys (signing and anchor encryption), approximately $2/month initially, plus one ledger-writer secret at approximately $0.40/month. S3 anchor/log storage and service requests are additional. Seven-year COMPLIANCE anchor versions cannot be deleted early, and the encryption/signing keys must remain available; stack removal retains these resources. The anchor CMK rotates automatically, which can add future key-version charges. These amounts are not deducted again from the Billing screenshot balance; fresh billing data is required for an updated remaining-credit figure.

[KMS pricing](https://aws.amazon.com/kms/pricing/) · [Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/)
