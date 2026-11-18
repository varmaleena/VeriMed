# Phase 1 appearance settings test

Open http://localhost:3000/settings after signing in. Settings is also available in the left navigation.

1. Choose **Dark** and **Compact**, then **Save preferences**. Expect an “Appearance saved” confirmation and the new theme.
2. Open Patients. Expect tighter row spacing with the same readable text size. Test the previous/next pagination arrows.
3. Open Worklist and return to Settings. Refresh the browser; both saved choices should persist.
4. Choose **Light** and **Comfortable**, save, and repeat the navigation check.
5. Choose **System** to follow the device's light/dark preference. Changing the device theme should update the app without another save.
6. Navigate the radio groups and Save button with the keyboard. Selected options have native radio indicators and a visible focus outline.
7. Sign out and open /settings. Expect a redirect to /login. Appearance choices remain available on the sign-in page.

Preferences are local to this browser and site, not an account profile or a cross-device setting. They contain only validated theme/density values in one-year, host-only, HttpOnly, SameSite=Lax cookies, with Secure enabled on HTTPS. The server renders the preference into the root document, preventing a client hydration theme flash. Invalid cookie values fall back to System/Comfortable. The save action independently checks authentication and token expiry, validates both choices, and rejects duplicate/unknown choice values.

The app shell, API reads and Settings save action share a server-only session guard; missing, expired or non-finite session expiries redirect to sign-in. This does not change Cognito or the owner-approved demo MFA configuration.

The scaffold ESLint configuration previously skipped TypeScript. This slice pins the verified Next.js lint configuration, enables Core Web Vitals/React and recommended TypeScript rules, and keeps generated files/build outputs out of lint. Strict types, a production build, actual lint, server-rendered preference fallbacks and anonymous Settings denial were checked locally. The signed-in save/navigation/keyboard flow remains for the owner to test.

No new AWS infrastructure is needed for this slice. Phase 1 is still in progress; hosted CI remains blocked on the repository remote.
