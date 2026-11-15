# Supabase server trust certificate

supabase-prod-ca-2021.crt is the public CA certificate the user downloaded from the
Supabase project's Database settings → SSL Configuration and supplied on 2026-11-15.
It contains no password or private key. It is used only for this application's Supabase
connection, not installed into a system-wide trust store.

- Subject/issuer: Supabase Root 2021 CA, Supabase Inc
- Validity: 2021-04-28 through 2031-04-26 (UTC)
- SHA-256 fingerprint: 807025ad50d4ed219d2c9c7d299c004f824eb00cf7f65afef607d07b72e6cafa

The connection checker validates the pinned fingerprint, CA flag, validity period and
self-signature before use. It retains sslmode=verify-full, including hostname validation.
Certificate renewal requires a reviewed replacement from Supabase's authenticated dashboard
and an updated fingerprint. No verification bypass or acceptance of a server-supplied root.

Official guidance:
https://github.com/supabase/supabase/blob/master/apps/docs/content/guides/platform/ssl-enforcement.mdx
