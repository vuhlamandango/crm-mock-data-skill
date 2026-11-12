#!/usr/bin/env python3
"""Build a Postman v2.1 collection that creates CRM / loan mock data.

Usage:  python -I build_collection.py spec.json out_collection.json

The spec is a small JSON file (see SKILL.md). The generated collection:
  * contains ONLY the requests the user selected, in dependency order
  * loops each request with pm.execution.setNextRequest until `count` is reached
  * stops the run on the first non-2xx response
  * keeps every created ID in a collection variable `ids_<key>` (JSON array)
  * prints a `MOCKDATA_SUMMARY {...}` line at the end of the run
  * never contains the ApplicationToken (collection variable `applicationToken`
    is left empty; supply it at run time)

Ported from the Data Retention/Deleter > Data Setup folder, with its bugs fixed
(see references/entities.md, "Known bugs fixed").
"""
import html
import json
import sys
from xml.sax.saxutils import escape as xml_escape

ZERO = "00000000-0000-0000-0000-000000000000"
SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
CRM_URL = "https://crmservice.{{env}}.vu.local/Crm.CoreService/api/Dynamics/"

ENVIRONMENTS = {
    "dev": {"env": "d", "loancreate_host": "https://vuhl-dev.redchimney.com"},
    "uat": {"env": "u", "loancreate_host": "https://vuhl-uat.redchimney.com"},
}

# key -> (request name, Dynamics logical name, CRM instance header or None)
SIMPLE = {
    "lead": ("Create Lead", "lead", None),
    "realty_lead": ("Create Realty Lead", "lead", "RSS"),
    "realty_contact": ("Create Realty Contact", "contact", "RSS"),
    "realty_opportunity": ("Create Realty Opportunity", "opportunity", "RSS"),
    "task": ("Create Task", "task", None),
    "realty_task": ("Create Realty Task", "task", "RSS"),
}
NAMES = {
    **{k: v[0] for k, v in SIMPLE.items()},
    "contact_opportunity": "Create Contact and Opportunity",
    "loan": "Create New Loan",
    "vu_loan": "Create vu_loan",
    "incident": "Create Incident",
    "realty_incident": "Create Realty Incident",
}
# Execution order (matches the original folder).
ORDER = ["lead", "realty_lead", "realty_contact", "realty_opportunity",
         "contact_opportunity", "loan", "vu_loan", "incident", "task",
         "realty_incident", "realty_task"]
# Entity -> id lists it writes.
IDS = {
    "lead": ["lead"], "realty_lead": ["realty_lead"],
    "realty_contact": ["realty_contact"],
    "realty_opportunity": ["realty_opportunity"],
    "contact_opportunity": ["contact", "opportunity"],
    "loan": ["loan", "loan_number"], "vu_loan": ["vu_loan"],
    "incident": ["incident"], "task": ["task"],
    "realty_incident": ["realty_incident"], "realty_task": ["realty_task"],
}
SEEDABLE = {"loan", "contact", "realty_contact"}
LOAN_DEFAULTS = {
    "opportunityId": "{{OpportunityId}}",
    "owningUserId": "{{owningUserId}}",
    "callingUserId": "{{owningUserId}}",
    "firstName": "{{$randomFirstName}}",
    "lastName": "{{$randomLastName}}",
    "address": "125 Test Ln",
    "city": "Testburg",
    "state": "MO",
    "zipCode": "65202",
    "loanType": "Conventional",
    "loanPurpose": "Purchase",
    "purchaseTimeframe": "Within a Month",
    "loanAmount": 100000.5,
    "purchaseState": "MO",
}


# --------------------------------------------------------------------------
# spec normalisation / dependency resolution
# --------------------------------------------------------------------------
def resolve(spec):
    ents = {k: dict(v) for k, v in spec.get("entities", {}).items() if int(v.get("count", 0)) > 0}
    unknown = set(ents) - set(ORDER)
    if unknown:
        raise SystemExit(f"Unknown entity keys: {sorted(unknown)}")
    seed = spec.get("seed", {})
    bad = set(seed) - SEEDABLE
    if bad:
        raise SystemExit(f"Cannot seed {sorted(bad)}; allowed: {sorted(SEEDABLE)}")
    notes = []

    def need(key, count, why):
        if key not in ents:
            ents[key] = {"count": count}
            notes.append(f"Added {NAMES[key]} x{count} ({why}).")

    # vu_loan needs a loan; loan needs a contact+opportunity; incident needs a contact.
    if "vu_loan" in ents and "loan" not in ents and not seed.get("loan"):
        need("loan", 1, "vu_loan needs a loan GUID")
    if "loan" in ents:
        # contact+opportunity are created 1:1 with loans (the original loop).
        n = int(ents["loan"]["count"])
        if "contact_opportunity" in ents and int(ents["contact_opportunity"]["count"]) != n:
            notes.append(f"Contact/opportunity count forced to {n} to match loans (they are created in pairs).")
        ents.setdefault("contact_opportunity", {})["count"] = n
    if "incident" in ents and "contact_opportunity" not in ents and not seed.get("contact"):
        need("contact_opportunity", 1, "incident needs a contact")
    if "realty_incident" in ents and "realty_contact" not in ents and not seed.get("realty_contact"):
        need("realty_contact", 1, "realty incident needs a realty contact")
    for k in ents:
        ents[k]["count"] = int(ents[k]["count"])
    return ents, seed, notes


# --------------------------------------------------------------------------
# value / attribute encoding
# --------------------------------------------------------------------------
def classify(v):
    """-> (kind, value). Typed values are dicts: {"type": "...", "value": ...}."""
    if isinstance(v, dict):
        return v.get("type", "string"), v
    if isinstance(v, bool):
        return "boolean", v
    if isinstance(v, int):
        return "int", v
    if isinstance(v, float):
        return "decimal", v
    return "string", v


def is_simple(fields):
    """Fields that can ride in the flat-JSON Create body."""
    return all(not isinstance(v, dict) for v in (fields or {}).values())


def attr_xml(key, v):
    kind, raw = classify(v)
    k = xml_escape(key)
    xs = 'xmlns:c="http://www.w3.org/2001/XMLSchema"'

    def prim(t, val):
        if isinstance(val, bool):
            val = "true" if val else "false"
        return (f'<KeyValuePairOfstringanyType><a:key>{k}</a:key>'
                f'<a:value i:type="c:{t}" {xs}>{xml_escape(str(val))}</a:value></KeyValuePairOfstringanyType>')

    if kind in ("string", "int", "decimal", "boolean", "dateTime"):
        return prim(kind, raw["value"] if isinstance(raw, dict) else raw)
    if kind == "optionset":
        return (f'<KeyValuePairOfstringanyType><a:key>{k}</a:key><a:value i:type="b:OptionSetValue">'
                f'<Value>{int(raw["value"])}</Value></a:value></KeyValuePairOfstringanyType>')
    if kind == "money":
        return (f'<KeyValuePairOfstringanyType><a:key>{k}</a:key><a:value i:type="b:Money">'
                f'<Value>{xml_escape(str(raw["value"]))}</Value></a:value></KeyValuePairOfstringanyType>')
    if kind == "ref":
        return (f'<KeyValuePairOfstringanyType><a:key>{k}</a:key><a:value i:type="b:EntityReference">'
                f'<Id>{xml_escape(str(raw["id"]))}</Id>'
                f'<KeyAttributes xmlns:d="http://schemas.microsoft.com/xrm/7.1/Contracts"/>'
                f'<LogicalName>{xml_escape(raw["entity"])}</LogicalName><Name i:nil="true"/>'
                f'<RowVersion i:nil="true"/></a:value></KeyValuePairOfstringanyType>')
    raise SystemExit(f"Unsupported field type '{kind}' for field '{key}'")


def create_request_xml(logical, id_expr, attrs):
    attrs_xml = "".join(attr_xml(k, v) for k, v in attrs.items())
    attrs_xml = f"<Attributes>{attrs_xml}</Attributes>" if attrs_xml else "<Attributes/>"
    return (
        '<OrganizationRequest i:type="c:CreateRequest" xmlns="http://schemas.microsoft.com/xrm/2012/Contracts" '
        'xmlns:c="Microsoft.Xrm.Sdk.Messages"><Parameters xmlns="http://schemas.microsoft.com/xrm/2011/Contracts">'
        '<KeyValuePairOfstringanyType><a:key>Target</a:key><a:value i:type="b:Entity">'
        f'{attrs_xml}<FormattedValues/><Id>{id_expr}</Id>'
        '<KeyAttributes xmlns:d="http://schemas.microsoft.com/xrm/7.1/Contracts"/>'
        f'<LogicalName>{logical}</LogicalName><RowVersion i:nil="true"/></a:value></KeyValuePairOfstringanyType>'
        '</Parameters><RequestId i:nil="true" xmlns="http://schemas.microsoft.com/xrm/2011/Contracts"/>'
        '<RequestName xmlns="http://schemas.microsoft.com/xrm/2011/Contracts">Create</RequestName></OrganizationRequest>'
    )


def transaction_payload(create_requests):
    inner = (
        '<ExecuteTransactionRequest xmlns="http://schemas.microsoft.com/xrm/2011/Contracts" '
        'xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
        '<Parameters xmlns:a="http://schemas.datacontract.org/2004/07/System.Collections.Generic">'
        '<KeyValuePairOfstringanyType><a:key>Requests</a:key>'
        '<a:value i:type="b:OrganizationRequestCollection" xmlns:b="Microsoft.Xrm.Sdk">'
        + "".join(create_requests) +
        '</a:value></KeyValuePairOfstringanyType></Parameters><RequestId i:nil="true"/>'
        '<RequestName>ExecuteTransaction</RequestName></ExecuteTransactionRequest>'
    )
    return (
        '<CoreServicePayload xmlns="http://schemas.datacontract.org/2004/07/Crm.CoreServiceConnector.Models" '
        'xmlns:i="http://www.w3.org/2001/XMLSchema-instance"><AssemblyName>Microsoft.Xrm.Sdk</AssemblyName>'
        '<ObjectType>Microsoft.Xrm.Sdk.Messages.ExecuteTransactionRequest</ObjectType>'
        f'<Xml>{html.escape(inner, quote=False)}</Xml></CoreServicePayload>'
    )


def ref(entity, var):
    return {"type": "ref", "entity": entity, "id": "{{" + var + "}}"}


# --------------------------------------------------------------------------
# script snippets
# --------------------------------------------------------------------------
JS_HELPERS = """\
const arr = (k) => { try { return JSON.parse(pm.collectionVariables.get(k) || '[]'); } catch (e) { return []; } };
const push = (k, v) => { const a = arr(k); a.push(v); pm.collectionVariables.set(k, JSON.stringify(a)); };
const made = (k) => parseInt(pm.collectionVariables.get('made_' + k) || '0', 10);
const bump = (k) => pm.collectionVariables.set('made_' + k, String(made(k) + 1));
const want = (k) => parseInt(pm.collectionVariables.get('count_' + k) || '0', 10);
const summary = () => { const o = {}; pm.collectionVariables.toObject && Object.entries(pm.collectionVariables.toObject()).forEach(([k, v]) => { if (k.startsWith('ids_')) { try { o[k.slice(4)] = JSON.parse(v); } catch (e) { o[k.slice(4)] = v; } } }); return o; };
const finish = (ok, why) => { console.log('MOCKDATA_SUMMARY ' + JSON.stringify({ ok: ok, reason: why || null, ids: summary() })); pm.collectionVariables.unset('_runStarted'); pm.execution.setNextRequest(null); };
"""


def lines(s):
    return s.rstrip("\n").split("\n")


def prereq_guard(all_id_keys, seeded):
    resets = "\n".join(
        f"  pm.collectionVariables.set('ids_{k}', '[]'); pm.collectionVariables.set('made_{k}', '0');"
        for k in all_id_keys if k not in seeded)
    return (
        "if (!pm.collectionVariables.get('_runStarted')) {\n"
        f"{resets}\n"
        "  pm.collectionVariables.set('_runStarted', '1');\n}\n"
    )


def loop_test(key, name, next_name, extract, extra="", is_first=False, delay=False):
    """Post-response script: record id, count, loop or move on, stop on failure.

    extract: JS expression (string) evaluating to the new id.
    """
    nxt = f"pm.execution.setNextRequest({json.dumps(next_name)});" if next_name else "finish(true);"
    return JS_HELPERS + f"""
pm.test('{name}: status is 2xx', () => pm.expect(pm.response.code).to.be.within(200, 299));
if (pm.response.code < 200 || pm.response.code >= 300) {{
  console.error('{name} failed: HTTP ' + pm.response.code + ' ' + pm.response.text().slice(0, 500));
  finish(false, '{name} returned HTTP ' + pm.response.code);
}} else {{
  let id = null;
  try {{ id = {extract}; }} catch (e) {{}}
  if (!id) {{
    finish(false, '{name}: could not read the new record id from the response');
  }} else {{
    push('ids_{key}', id); bump('{key}');
{extra}
    if (made('{key}') < want('{key}')) {{ pm.execution.setNextRequest({json.dumps(name)}); }}
    else {{ {nxt} }}
  }}
}}
"""


def build(spec):
    ents, seed, notes = resolve(spec)
    seq = [k for k in ORDER if k in ents]
    envinfo = ENVIRONMENTS[spec.get("environment", "dev").lower()]
    items, variables = [], []

    all_id_keys = sorted({i for k in seq for i in IDS[k]} | set(seed))
    seeded = set(seed)

    def nxt(i, key):
        # loan/contact pairing is handled explicitly below
        return NAMES[seq[i + 1]] if i + 1 < len(seq) else None

    for i, key in enumerate(seq):
        name = NAMES[key]
        e = ents[key]
        fields = e.get("fields", {})
        pre = ""
        if i == 0:
            pre += prereq_guard(all_id_keys, seeded)
        headers = [{"key": "ApplicationToken", "value": "{{applicationToken}}"}]
        item = {"name": name, "protocolProfileBehavior": {"disableBodyPruning": True}}

        # ---------------- simple CRM entities ----------------
        if key in SIMPLE:
            _, logical, inst = SIMPLE[key]
            if inst:
                headers.append({"key": "CrmInstance", "value": inst})
            if is_simple(fields):
                body = {"LogicalName": logical, "Id": ZERO, **fields}
                req = {"method": "POST", "url": CRM_URL + "Create", "header": headers,
                       "body": {"mode": "raw", "raw": json.dumps(body, indent=2),
                                "options": {"raw": {"language": "json"}}}}
                extract = "pm.response.json()"
            else:  # typed fields -> ExecuteTransaction XML with a client-side GUID
                pre += "pm.collectionVariables.set('_newId', pm.variables.replaceIn('{{$guid}}'));\n"
                payload = transaction_payload([create_request_xml(logical, "{{_newId}}", fields)])
                req = {"method": "POST", "url": CRM_URL + "Execute?useRetries=True", "header": headers,
                       "body": {"mode": "raw", "raw": payload, "options": {"raw": {"language": "xml"}}}}
                extract = "pm.collectionVariables.get('_newId')"
            test = loop_test(key, name, nxt(i, key), extract)

        # ---------------- contact + opportunity ----------------
        elif key == "contact_opportunity":
            has_loan = "loan" in ents
            pre += ("pm.collectionVariables.set('ContactID', pm.variables.replaceIn('{{$guid}}'));\n"
                    "pm.collectionVariables.set('OpportunityId', pm.variables.replaceIn('{{$guid}}'));\n")
            opp_fields = {"customerid": ref("contact", "ContactID"), **e.get("opportunity_fields", {})}
            payload = transaction_payload([
                create_request_xml("contact", "{{ContactID}}", e.get("contact_fields", {})),
                create_request_xml("opportunity", "{{OpportunityId}}", opp_fields)])
            req = {"method": "POST", "url": CRM_URL + "Execute?useRetries=True", "header": headers,
                   "body": {"mode": "raw", "raw": payload, "options": {"raw": {"language": "xml"}}}}
            nxt_name = NAMES["loan"] if has_loan else nxt(i, key)
            delay = ("    if (parseInt(pm.collectionVariables.get('delay_ms') || '0', 10) > 0) "
                     "{ await new Promise(r => setTimeout(r, parseInt(pm.collectionVariables.get('delay_ms'), 10))); }\n"
                     if has_loan else "")
            test = JS_HELPERS + f"""
pm.test('{name}: status is 2xx', () => pm.expect(pm.response.code).to.be.within(200, 299));
if (pm.response.code < 200 || pm.response.code >= 300) {{
  console.error('{name} failed: HTTP ' + pm.response.code + ' ' + pm.response.text().slice(0, 500));
  finish(false, '{name} returned HTTP ' + pm.response.code);
}} else {{
  push('ids_contact', pm.collectionVariables.get('ContactID'));
  push('ids_opportunity', pm.collectionVariables.get('OpportunityId'));
  bump('contact_opportunity');
{delay}  {"pm.execution.setNextRequest(" + json.dumps(nxt_name) + ");" if nxt_name and has_loan else
          ("if (made('contact_opportunity') < want('contact_opportunity')) { pm.execution.setNextRequest(" + json.dumps(name) + "); } else { " + ("pm.execution.setNextRequest(" + json.dumps(nxt_name) + ");" if nxt_name else "finish(true);") + " }")}
}}
"""

        # ---------------- loan ----------------
        elif key == "loan":
            body = {**LOAN_DEFAULTS, **e.get("fields", {})}
            req = {"method": "POST", "url": "{{loancreate_host}}/apps/loancreate/loans", "header": [],
                   "body": {"mode": "raw", "raw": json.dumps(body, indent=2),
                            "options": {"raw": {"language": "json"}}}}
            after = nxt(i, key)
            test = JS_HELPERS + f"""
pm.test('{name}: status is 2xx', () => pm.expect(pm.response.code).to.be.within(200, 299));
if (pm.response.code < 200 || pm.response.code >= 300) {{
  console.error('{name} failed: HTTP ' + pm.response.code + ' ' + pm.response.text().slice(0, 500));
  finish(false, '{name} returned HTTP ' + pm.response.code);
}} else {{
  let item = null;
  try {{ item = pm.response.json().data.items[0]; }} catch (e) {{}}
  if (!item || !item.loanGuid) {{
    finish(false, '{name}: response had no data.items[0].loanGuid');
  }} else {{
    push('ids_loan', item.loanGuid); push('ids_loan_number', item.loanNumber); bump('loan');
    if (made('loan') < want('loan')) {{ pm.execution.setNextRequest({json.dumps(NAMES["contact_opportunity"])}); }}
    else {{ {"pm.execution.setNextRequest(" + json.dumps(after) + ");" if after else "finish(true);"} }}
  }}
}}
"""

        # ---------------- vu_loan ----------------
        elif key == "vu_loan":
            pre += ("{\n" + JS_HELPERS.split("const summary")[0] +
                    "  const loans = arr('ids_loan');\n"
                    "  if (!loans.length) { throw new Error('No loan GUIDs available for vu_loan'); }\n"
                    "  pm.collectionVariables.set('CurrentLoanGuid', loans[made('vu_loan') % loans.length]);\n}\n")
            body = {"LogicalName": "vu_loan", "Id": ZERO, "vu_losid_calc": "{{CurrentLoanGuid}}", **fields}
            if not is_simple(fields):
                raise SystemExit("vu_loan fields must be plain string/number/bool values")
            req = {"method": "POST", "url": CRM_URL + "Create", "header": headers,
                   "body": {"mode": "raw", "raw": json.dumps(body, indent=2),
                            "options": {"raw": {"language": "json"}}}}
            test = loop_test(key, name, nxt(i, key), "pm.response.json()")

        # ---------------- incident / realty incident ----------------
        elif key in ("incident", "realty_incident"):
            realty = key == "realty_incident"
            src = "ids_realty_contact" if realty else "ids_contact"
            if realty:
                headers.append({"key": "CrmInstance", "value": "RSS"})
            pre += ("{\n" + JS_HELPERS.split("const summary")[0] +
                    f"  const c = arr('{src}');\n"
                    f"  if (!c.length) {{ throw new Error('No contact available for {name}'); }}\n"
                    "  pm.collectionVariables.set('_customerId', c[c.length - 1]);\n}\n"
                    "pm.collectionVariables.set('_newId', pm.variables.replaceIn('{{$guid}}'));\n")
            attrs = {"customerid": ref("contact", "_customerId"), **fields}
            payload = transaction_payload([create_request_xml("incident", "{{_newId}}", attrs)])
            req = {"method": "POST", "url": CRM_URL + "Execute?useRetries=True", "header": headers,
                   "body": {"mode": "raw", "raw": payload, "options": {"raw": {"language": "xml"}}}}
            test = loop_test(key, name, nxt(i, key), "pm.collectionVariables.get('_newId')")

        req.setdefault("description", f"Generated by the crm-mock-data skill. Creates {e['count']} record(s).")
        item["request"] = req
        ev = []
        if pre:
            ev.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": lines(pre)}})
        ev.append({"listen": "test", "script": {"type": "text/javascript", "exec": lines(test)}})
        item["event"] = ev
        items.append(item)
        # per-entity counter
        variables.append({"key": f"count_{key}", "value": str(e["count"])})
        if key not in ("loan",):
            variables.append({"key": f"made_{key}", "value": "0"})
        else:
            variables.append({"key": "made_loan", "value": "0"})
    # contact_opportunity / loan share counts when paired
    for k in all_id_keys:
        variables.append({"key": f"ids_{k}", "value": json.dumps(seed.get(k, []))})
        if k in seeded:
            pass
    for k in ("contact_opportunity",):
        pass
    variables += [
        {"key": "env", "value": envinfo["env"]},
        {"key": "loancreate_host", "value": envinfo["loancreate_host"]},
        {"key": "applicationToken", "value": ""},
        {"key": "owningUserId", "value": spec.get("owning_user_id", "f5aa8695-3098-e311-bfc1-6c3be5a81fe0")},
        {"key": "delay_ms", "value": str(spec.get("delay_ms", 5000))},
    ]
    # de-duplicate variables keeping first
    seen, uniq = set(), []
    for v in variables:
        if v["key"] not in seen:
            seen.add(v["key"]); uniq.append(v)

    coll = {
        "info": {"name": spec["collection_name"], "schema": SCHEMA,
                 "description": ("Mock CRM / loan data generator. Run the whole collection in order "
                                 "(Collection Runner, Postman CLI or Newman) with env + applicationToken set.")},
        "item": items,
        "variable": uniq,
    }
    return coll, notes, seq


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    coll, notes, seq = build(spec)
    json.dump(coll, open(sys.argv[2], "w", encoding="utf-8"), indent=2)
    print(json.dumps({"requests": [NAMES[k] for k in seq], "notes": notes}, indent=2))
