# ChartVigil authentication slice

The working display name is ChartVigil. Repository packages and AWS resources retain their VeriMed identifiers. Name availability has not been legally cleared.
The owner requested starting the next slice while Phase 0 acceptance remains open.

Start the local app from the repository root after the dev identity stack and local environment are configured.

```powershell
& 'C:\Program Files\nodejs\npm.cmd' --prefix apps/web run dev
```

Open http://localhost:3000/login and use the Cognito invitation delivered to your email.

1. Open /worklist in a private browser window. Expect a redirect to /login.
2. Choose hospital sign-in. Enter the invited email and temporary password.
3. Set a new password, enroll an authenticator app, and enter its TOTP.
4. Expect the protected shell with the configured dev tenant name and Worklist connection status.
5. Sign out. Refresh /worklist and expect another redirect to /login.
6. Sign in again. Expect a fresh Cognito login and a TOTP challenge.
7. After the fifteen-minute token lifetime, request /worklist. Expect login to be required again.
8. Check /api/auth/session. It must contain no Cognito access, ID, or refresh token.

Human TOTP and visual checks remain pending until performed. The app currently runs locally.
The dev identity stack deployed successfully and the requested test invitation was issued.
The identity stack is separate so the first slice can be verified before adding ECS, the API and clinical data.
The default Next.js and Auth.js error handling is provisional. PHI scrubbing and distributed tracing remain open Phase 1 work.
