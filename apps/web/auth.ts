import NextAuth from "next-auth";
import Cognito from "next-auth/providers/cognito";

export const { handlers, auth, signIn, signOut } = NextAuth(() => ({
  providers: [
    Cognito({
      clientId: process.env.AUTH_COGNITO_ID,
      clientSecret: process.env.AUTH_COGNITO_SECRET,
      issuer: process.env.AUTH_COGNITO_ISSUER,
      checks: ["pkce", "state", "nonce"],
      authorization: { params: { scope: "openid profile", prompt: "login" } },
    }),
  ],
  session: { strategy: "jwt", maxAge: 900 },
  pages: { signIn: "/login" },
  callbacks: {
    jwt({ token, account, profile }) {
      if (account && profile) {
        token.accessToken = account.access_token;
        if (profile.iss !== process.env.AUTH_COGNITO_ISSUER)
          throw new Error("Unexpected identity issuer");
        token.roles = Array.isArray(profile["cognito:groups"])
          ? profile["cognito:groups"].filter(
              (role): role is string => typeof role === "string",
            )
          : [];
        token.expiresAt = account.expires_at ?? 0;
      }
      return token;
    },
    session({ session, token }) {
      session.user.roles = Array.isArray(token.roles)
        ? (token.roles as string[])
        : [];
      session.user.expiresAt =
        typeof token.expiresAt === "number" ? token.expiresAt : 0;
      return session;
    },
  },
}));
