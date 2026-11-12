# Entity reference (from Data Retention/Deleter > Data Setup)

Source: Lightspeed workspace, collection `Data Retention/Deleter`, folder `Data Setup`
(read 2026-11-12). Hosts: CRM `https://crmservice.{{env}}.vu.local/Crm.CoreService/api/Dynamics/`
with `env` = `d` (Dev) or `u` (UAT); loan service `{{loancreate_host}}` =
`https://vuhl-dev.redchimney.com` or `https://vuhl-uat.redchimney.com`.
Every CRM call sends an `ApplicationToken` header. `CrmInstance: RSS` routes to the Realty CRM;
no header means the default CRM.

| Key | Request | Instance | Endpoint | Needs | Writes |
|---|---|---|---|---|---|
| lead | Create Lead | default | `Create` (JSON) | none | `ids_lead` |
| realty_lead | Create Realty Lead | RSS | `Create` (JSON) | none | `ids_realty_lead` |
| realty_contact | Create Realty Contact | RSS | `Create` (JSON) | none | `ids_realty_contact` |
| realty_opportunity | Create Realty Opportunity | RSS | `Create` (JSON) | none (not linked to a contact) | `ids_realty_opportunity` |
| contact_opportunity | Create Contact and Opportunity | default | `Execute` ExecuteTransaction XML: contact, then opportunity with `customerid` -> contact | none | `ids_contact`, `ids_opportunity` |
| loan | Create New Loan | loan service | `POST /apps/loancreate/loans` | contact+opportunity (uses `OpportunityId`) | `ids_loan`, `ids_loan_number` |
| vu_loan | Create vu_loan | default | `Create` (JSON) with `vu_losid_calc` = loan GUID | loan | `ids_vu_loan` |
| incident | Create Incident | default | `Execute` XML, `customerid` -> last contact | contact | `ids_incident` |
| task | Create Task | default | `Create` (JSON) | none (not linked) | `ids_task` |
| realty_incident | Create Realty Incident | RSS | `Execute` XML, `customerid` -> last realty contact | realty contact | `ids_realty_incident` |
| realty_task | Create Realty Task | RSS | `Create` (JSON) | none (not linked) | `ids_realty_task` |

Original run order and counts: Lead x2, Realty Lead x1, Realty Contact x3, Realty Opportunity
(configured x2), then [Contact+Opportunity -> Loan] x3, vu_loan x12, Incident x2, Task x2,
Realty Incident x1, Realty Task x1. Those counts are now user-supplied.

## How the original worked
- Each request's *test script* sets the next request with `pm.execution.setNextRequest`
  and loops until a `MAX_ENTRIES` constant is reached, so the folder only chains when run
  in the Runner/CLI.
- `Create` calls are blank shells: `{"LogicalName": "...", "Id": "000..."}` with no fields.
  Extra top-level JSON properties are accepted as attributes (the `vu_loan` request sends
  `vu_losid_calc` this way), which is how the skill sets simple fields.
- Contact/opportunity GUIDs are generated client-side (`{{$guid}}`) and sent in the XML.
- Loan service body defaults: `owningUserId`/`callingUserId` `f5aa8695-3098-e311-bfc1-6c3be5a81fe0`,
  random first/last name, `125 Test Ln`, `Testburg`, `MO`, `65202`, `Conventional`, `Purchase`,
  `Within a Month`, `loanAmount` 100000.5, `purchaseState` `MO`. Response:
  `data.items[0].loanGuid` and `.loanNumber`.
- A 5-second delay (via `postman-echo.com/delay/5`) follows contact+opportunity creation,
  presumably so CRM syncs before the loan is created. The skill uses `delay_ms` instead.
- Fresh Start cleared the state variables; Log Entities printed them via postman-echo.
  The skill resets state at run start and prints a `MOCKDATA_SUMMARY` line instead, so
  nothing depends on an external site.

## Known bugs fixed in the generated collection
1. Realty Opportunity compared the GUID *string length* (36) to the count, so it always
   made one record regardless of the configured count.
2. vu_loan x12 against 3 loans read `loanGuids[3..11]` = undefined, leaving vu_loans 4-12
   with no loan GUID. Now round-robin over the available loans.
3. State variables mixed arrays, JSON strings and comma strings. All are JSON arrays now.
4. Log Entities read `ServicingNumbers`, which nothing set (dropped).
5. Only two requests stopped the run on failure. Now every request does.
6. The `ApplicationToken` was hardcoded in every request header. Now `{{applicationToken}}`.
7. Create Lead had a stray empty header; request descriptions were copy-paste wrong.
8. Prod and Local environments exist beside Dev/UAT; the skill only offers Dev and UAT.

## Open questions to verify with the team
- Whether the JSON `Create` endpoint accepts arbitrary attributes beyond the `vu_loan` one
  seen here (assumed yes).
- Optionset/money encodings in the XML path (unverified; strings and entity references are
  verified from the original).
- Whether Newman/Postman CLI honors `pm.execution.setNextRequest` in the installed version.
  Symptom if not: only one record per request type.
