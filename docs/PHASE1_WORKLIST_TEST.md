# Worklist slice

The Worklist reads the cell's real Aurora PostgreSQL database through the protected API.
An empty database returns an empty list. No encounter records are fabricated.

1. Restart the local Next.js app after the CELL_API_URL environment setting is written.
2. Sign out and sign in again. This renews the server-only Cognito token in the encrypted session.
3. Open /worklist. Expect the empty Worklist with a status filter.
4. Apply the Signed filter. Expect an empty filtered view.
5. Sign out and reopen /worklist. Expect a redirect to /login.
6. After Aurora pauses, the API retries its wake-up response for up to fourteen seconds. If the service still cannot respond, the Worklist shows an inline availability message with Try again.

The backend has unit tests for anonymous denial, denied-role access and transaction rollback.
The live isolation runner inserts two tenants inside a transaction and verifies that the API database role cannot see the other tenant. All test rows are rolled back.
The live API runner tests anonymous API Gateway denial and directly invokes the deployed Lambda with representative Gateway events to exercise the real Verified Permissions and database path.
The direct Lambda check does not replace the human Cognito browser test.

The dev database auto-pauses after five minutes and is limited to one ACU. Storage, secrets and KMS continue to incur charges during pause.
The runtime deviations and remaining production work are recorded in ADR 008.
Encounter ingestion and the simulator are later-phase workflows. This slice displays their real stored records when those workflows are implemented.
The timestamp presentation currently uses Asia/Kolkata for the owner's demo environment.
