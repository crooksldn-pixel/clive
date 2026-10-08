import { currentUser, HttpError, json, readJson, wrap } from "../lib/http.ts";

/**
 * portalCheckAvailable: { username } or { code } → { available }.
 * Lets the portal check uniqueness once influencer records are private.
 */
export const portalCheckAvailable = wrap(async (req, deps) => {
  const body = await readJson(req);
  const user = await currentUser(deps);
  if (!user) throw new HttpError(401, "Sign in first.", "unauthenticated");
  const db = deps.base44.asServiceRole.entities;
  const mine = (await db.Influencer.filter({ email: user.email }))[0];

  if (typeof body.username === "string") {
    const username = body.username.toLowerCase().replace(/[^a-z0-9._]/g, "");
    if (!username) return json({ available: false });
    const taken = (await db.Influencer.filter({ username })).some((i) => i.email !== user.email);
    return json({ available: !taken, username });
  }
  if (typeof body.code === "string") {
    const code = body.code.toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (!code) return json({ available: false });
    const taken = (await db.AffiliateCode.filter({ code })).some((c) => !mine || c.influencerId !== mine.id);
    return json({ available: !taken, code, suggestion: taken ? `${code}2` : undefined });
  }
  throw new HttpError(400, "Send { username } or { code }.", "bad_request");
});
