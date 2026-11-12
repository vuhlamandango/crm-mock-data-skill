---
name: crm-mock-data
description: Creates mock test data (leads, contacts, opportunities, loans, vu_loans, incidents, tasks, and their Realty/RSS equivalents) in the Dev or UAT CRM instances. Interviews the user about what data they need and which fields to set, builds a new Postman collection with only the needed requests in the Postman workspace they choose, then runs it and reports the created IDs. Use when someone says "create test data", "mock data", "seed CRM", "I need a test loan/lead/contact/opportunity", or "set up data for testing" at Veterans United. Dev and UAT only, never Prod.
---

# CRM mock data

Turns "I need some test data" into a Postman collection the user owns, then runs it.
It replaces hand-running the **Data Setup** folder of *Data Retention/Deleter* in the
Lightspeed Postman workspace. Entity behavior, dependencies and the bugs fixed from the
original are in `references/entities.md`: read it before building a spec.

Bundled files (paths relative to this skill folder):
- `scripts/build_collection.py` generates the Postman v2.1 collection from a spec
- `scripts/simulate_run.js` dry-runs a generated collection with a fake Postman sandbox (no network)
- `examples/example-spec.json` a complete spec to copy from

## Hard rules

- **Dev and UAT only.** If the user asks for Prod or Local, decline and say why.
- **Never put the ApplicationToken anywhere durable**: not in the spec, the collection,
  the chat, or a file. The collection ships with an empty `applicationToken` variable. At
  run time read it from the user's shell environment (`APPLICATION_TOKEN`). If it is not
  set, ask the user to set it themselves; do not ask them to paste it.
- **Two confirmations, each explicit**: (1) before creating the collection in Postman,
  (2) before running it, because running writes real records into a shared CRM.
- Never default the workspace. The user picks it. Do not assume Lightspeed.

## Workflow

### 1. Check Postman access
Call `getAuthenticatedUser`. If it fails, tell the user the Postman connector is not
connected and stop.

### 2. Interview the user
Ask in plain language, a few questions at a time. Use AskUserQuestion when options are
fixed, free text otherwise.

1. **Environment**: Dev or UAT.
2. **What are they trying to create?** Offer this menu (multi-select) and describe each in
   one line; let them describe a scenario instead ("a borrower with a loan and two
   incidents") and you map it:
   - Leads (default CRM) / Realty leads (RSS CRM)
   - Contact + opportunity pairs (default CRM)
   - Loans (via the loan creation service; each needs a contact + opportunity)
   - vu_loan records (CRM records tied to a loan GUID)
   - Incidents / Tasks (default CRM) and Realty incidents / tasks (RSS CRM)
   - Realty contacts / opportunities (RSS CRM)
3. **How many of each.**
4. **Fields**: for every selected entity ask "Do you need any specific field values, or is
   a blank/default record fine?" Field keys are CRM *logical names* (`firstname`,
   `emailaddress1`, ...). The skill cannot validate them against CRM, so ask the user to
   name them exactly. For loans, fields are loan-service JSON keys (`firstName`,
   `loanAmount`, `state`, ...; defaults in `references/entities.md`). Postman dynamic
   variables like `{{$randomFirstName}}` work in string values.
5. **Existing records**: if they only need incidents/vu_loans against records that already
   exist, accept existing contact GUIDs, realty contact GUIDs or loan GUIDs (`seed`).
6. **Collection name**: ask what to call the new collection. Suggest nothing; use their words.
7. **Workspace**: list candidates with `getWorkspaces`. First call `getAuthenticatedUser`,
   then `getWorkspaces` with `createdBy` set to the user's id (and `type: personal` if
   they say "my personal workspace"). If they name a team workspace, find it by name
   (page with `cursor`). Present a short numbered list and have them choose. Remember the
   workspace *id*.

### 3. Build the spec and the collection
Write `spec.json` in the scratchpad directory (shape below), then:

```bash
python -I <skill>/scripts/build_collection.py <scratch>/spec.json <scratch>/collection.json
```

It prints the request order and any **notes** (auto-added prerequisites, forced counts).
Show those to the user. Then run the dry run to prove the logic loops correctly:

```bash
node <skill>/scripts/simulate_run.js <scratch>/collection.json
```

Expect the printed order to match the plan and a final `MOCKDATA_SUMMARY` with `"ok":true`.
If not, fix the spec or report the bug; do not continue.

### 4. Confirm, then create the collection
Show a summary table (environment, entity, count, custom fields, workspace, collection
name). Ask for an explicit yes. On yes, read `collection.json` and call
`createCollection` with `collection` = that JSON object and `workspace` = the chosen id.
Report the collection name and link/id. Do not store the token (the variable is empty).

### 5. Confirm, then run
Say exactly what the run will write ("3 leads, 2 loans... in **UAT**") and get an
explicit yes. Preflight:

1. **Network**: the CRM hosts are internal (`crmservice.d.vu.local` / `.u.vu.local`). Run
   `nslookup crmservice.<d|u>.vu.local`. If it does not resolve, tell the user they need
   to be on the VPN/corporate network and stop.
2. **Token**: confirm `APPLICATION_TOKEN` is set in the shell without printing it
   (`[ -n "$APPLICATION_TOKEN" ] && echo set`).
3. **Runner**, first that exists:
   - Postman CLI: `postman collection run <collection-uid> --env-var "applicationToken=$APPLICATION_TOKEN"`
     (needs `postman login`).
   - Newman: `npx newman run <scratch>/collection.json --env-var "applicationToken=$APPLICATION_TOKEN"`.
     `npx` downloads Newman from npm; tell the user and get a yes first.
   - Otherwise give the user the Postman Collection Runner steps (open collection, Run,
     set the `applicationToken` variable first).

If the user customized fields, recommend a first run with every count set to 1 and ask
them to eyeball one record in CRM before the full run.

### 6. Report
Parse the `MOCKDATA_SUMMARY {...}` line from the output (it prints even on failure and
says which request failed and why). Present a table of entity -> IDs. Loans include
loan numbers (`loan_number`). Offer to save the IDs to a file. Mention that cleanup can
be done with the delete requests in *Data Retention/Deleter* (NextGenEncompassGateway and
MortDocs folders) using these IDs. If the run failed part way, say which records were
already created (they are NOT rolled back) and offer to re-run only the missing pieces.

## Spec shape

```json
{
  "collection_name": "<what the user asked for>",
  "environment": "dev",
  "owning_user_id": "optional CRM user GUID for loans",
  "delay_ms": 5000,
  "entities": {
    "lead":    {"count": 2, "fields": {"firstname": "Ada", "lastname": "{{$randomLastName}}"}},
    "contact_opportunity": {"count": 3,
        "contact_fields": {"firstname": "Pat"},
        "opportunity_fields": {"name": "Test opp"}},
    "loan":    {"count": 3, "fields": {"loanAmount": 250000, "state": "KS"}},
    "vu_loan": {"count": 5},
    "incident": {"count": 2, "fields": {"title": "Test case"}},
    "task": {"count": 1}
  },
  "seed": {"loan": ["<existing loan guid>"]}
}
```

Entity keys: `lead`, `realty_lead`, `realty_contact`, `realty_opportunity`,
`contact_opportunity`, `loan`, `vu_loan`, `incident`, `task`, `realty_incident`,
`realty_task`. Seed keys: `loan`, `contact`, `realty_contact`.

Field values: plain string/number/bool go straight into the request. Typed values use
`{"type": "optionset|money|ref|int|decimal|boolean|dateTime|string", ...}`:
`{"type":"optionset","value":1}`, `{"type":"money","value":2500}`,
`{"type":"ref","entity":"account","id":"<guid>"}`. Typed values switch that entity to the
XML `ExecuteTransaction` path. This path is verified for strings and entity references
(the original used them); optionset and money encodings follow the Xrm SDK format but are
unverified against this CoreService, so always do the count-1 check first.

## Things to tell the user honestly

- Dependencies are added automatically (vu_loan -> loan -> contact+opportunity; incident
  -> contact; realty incident -> realty contact) and the notes say so.
- Contact/opportunity count follows the loan count because the original creates them in pairs.
- vu_loans are spread across the loans round-robin. The original left vu_loans 4-12 with
  no loan GUID; this is fixed.
- The run stops at the first failed request; earlier records remain.
- Custom field names are not validated until CRM accepts or rejects them.
