# External prerequisites (no secrets in chat)

Complete only the relevant service setup. Do not pay for services or enable trading.

1. **Network:** Review/save the draft in environment settings and publish the environment.
   It adds GitHub API, Google APIs/Docs, Yahoo, Alpha Vantage and official index/exchange/flow
   hosts while preserving package-manager presets. Runtime connectivity must be retested.
   Additional provider documentation hosts can be added after the permitted source is chosen.
2. **GitHub:** Confirm `kgmikhdad/portfolio` is private. Existing Git proxy access is used;
   do not supply a token merely because the GitHub API is currently blocked. Repository
   metadata, Actions runs and settings cannot yet be verified through that API. If push is
   rejected for workflow-file scope, authorize workflow writes through the supported GitHub
   connection. Do not change repository visibility without explicit approval.
3. **Google:** Use https://console.cloud.google.com/apis/library to enable Sheets and Drive
   APIs in your own project. Prefer workload identity federation or scoped OAuth. Grant the
   application access to the designated workbook and permission to copy that workbook;
   restrict Drive access with `drive.file` where the app has been granted that file, plus
   `spreadsheets` for updates. Do not grant general access to unrelated Drive content.
   Initial implementation takes an access token supplied by secure runtime injection; an
   unattended credential-refresh binding must be integrated before scheduling. Never paste
   tokens or service-account keys into chat. Backup/read verification precedes writes.
4. **Persistent PostgreSQL:** Choose an existing authorized database or supply its hostname
   and secure connection binding. No managed account or paid database was created. Restrict
   the paper role to the project database with TLS verification. Save `PAPER_DATABASE_URL`
   through https://github.com/kgmikhdad/portfolio/settings/secrets/actions in a `paper`
   environment; allowlist its host in cloud settings. Use a separate migration role.
5. **Market data and membership:** Supply permitted data access through the chosen provider's
   official portal and secure secret settings. Alpha Vantage registration:
   https://www.alphavantage.co/support/#api-key (key only if selected/coverage verified).
   Establish usage rights, Indian-market coverage, history and actual quotas. Obtain the
   authoritative dated Nifty500 Shariah constituent document, historical eligibility/calendar,
   corporate actions and authorized TRI benchmark. No paid subscription is required or approved
   by this code. Yahoo usage remains disabled until rights are established.
6. **Scheduling:** Keep `PAPER_PIPELINE_ENABLED` unset/false until persistent data, references,
   source finalization, monitoring and manual job verification work. No Work recurring-task
   tool is exposed in this session. Test the evidence queue/handoff manually before scheduling
   a qualitative task; do not infer that Work can push to GitHub.

Secure secret entry is a service-setting action, never an ordinary chat message. The concrete
next dependency is network access; existing account bindings should be rechecked after it is
applied before requesting any additional credential.
