# Patients slice

The owner approved a two-day AWS HealthLake test window, then recreation for recording.
This store contains AWS's Synthea preload and uses customer-managed KMS encryption.
Integrated NLP is disabled for this read-only patient view.
The current window expires November 20, 2026 at 18:34:54 IST (13:04:54 UTC); the teardown schedule is enabled.

1. Sign in at http://localhost:3000/login and choose Patients in the left navigation.
2. Expect live FHIR records with patient tokens, birth years and sex. Expand **View FHIR ID** to see the source resource identifier; it is not a patient-chart navigation link.
3. At the table footer, expect ‹ 1–20 ›. The previous arrow is disabled on the first page. Choose the next arrow and verify the records change and the range becomes 21–40.
4. Choose the previous arrow to return to 1–20. Check both arrows with keyboard navigation. While loading, both are disabled; a failed read retains the current page and displays an error. Refresh starts from the first page. A total appears only when the live FHIR search supplies one.
5. Open Worklist and verify that its real encounter list still loads.
6. Sign out and open /patients. Expect a redirect to /login.
7. After the displayed test-window expiry, expect an inline closed-window message.
8. Move to the second page, then choose **Refresh list**. Expect a fresh read, a new retrieval timestamp, and a return to 1–20. Refresh/pagination controls are disabled while a request is pending.
9. Scroll the table vertically. Its column headers remain visible and the pagination footer stays outside the scroll region. Tab into the table region to scroll with the keyboard, then tab to a record disclosure and expand it with Enter/Space.
10. Repeat in Light/Dark themes and Comfortable/Compact density. Check the narrower layout with horizontal scrolling; long FHIR identifiers wrap inside the disclosure.

FHIR names, addresses, full birth dates and external identifier fields are omitted from the response. The source FHIR resource ID remains available in the disclosure.
Tokens are derived from the cell tenant identifier and the FHIR resource identifier.
The API's IAM identity is limited to searching the configured datastore.
Its KMS decrypt/describe permissions are restricted to that datastore's encryption key and calls through HealthLake in the same account, as required by [AWS's encryption documentation](https://docs.aws.amazon.com/healthlake/latest/devguide/encryption-at-rest.html).
When deploying, supply `FHIR_KMS_KEY_ARN` and preserve `VERIMED_FHIR_EXPIRES_AT` as an ISO 8601 UTC string. PowerShell JSON date conversion must not localize this environment variable.
The direct Lambda live test verifies real FHIR reads, pagination and Verified Permissions denial. The human browser test additionally verifies the Cognito session path.

The displayed timestamp is when this app finished retrieving the page, not the date a patient record changed. Refresh restarts cursor navigation so old downstream cursors are discarded. Failed reads retain the prior rows with a visible stale-results warning; the successful retrieval timestamp remains unchanged. A request guard prevents overlapping refresh/pagination calls. No global search, sort or patient totals are inferred from a partial page.

The table review update passed lint, strict TypeScript and a production build. The browser was at sign-in during agent inspection, so the authenticated visual/keyboard flow remains for the owner to test.

The expiry is displayed in IST. EventBridge Scheduler is configured to delete only CellFhirDemo using CloudFormation's stored execution role. The scheduled deletion is a future action and must be checked after the window ends.
The application checks the same expiry and returns HTTP 410 after it.
To recreate for recording, deploy a fresh CellFhirDemo with a new expiry and update the API's FHIR configuration from its outputs.
