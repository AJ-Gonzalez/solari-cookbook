"""Form-field extraction and multi-page fill loop for application forms.

The fill layer is host-tolerant (greenhouse embed/main-frame, lever); the
submission layer is deliberately NOT automated — the driver reaches a
"filled and ready" state and the human performs the final submit (DESIGN.md).

Multi-page forms: the loop fills the fields it can see, clicks a
Next/Continue control when present, re-discovers, and only stops at a
Submit — so paginated questionnaires and post-apply steps are walked the
same way as single-page forms.

The human-in-loop contract: every field the answers bank can't resolve is
surfaced through `ask_callback` (the chat layer), and every answer the
human dictates is learned into the bank for reuse.
"""
import re
import time
from dataclasses import dataclass, field

from .answers import AnswersBank

DECLINE_PAT = re.compile(
    r"decline|none of the|not applicable|don't wish|do not want|prefer not",
    re.I)
EEO_PAT = re.compile(r"gender|ethnic|race|veteran|disability|identify", re.I)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
NEXT_PAT = re.compile(r"\b(next|continue)\b", re.I)
SUBMIT_PAT = re.compile(r"\b(submit|apply)\b", re.I)


@dataclass
class FormField:
    label: str
    kind: str                 # text | select | radio | checkbox | file | textarea
    options: list[str] = field(default_factory=list)
    required: bool = False
    locator_id: str = ""      # best selector hint for filling


def discover_fields(frame) -> list[FormField]:
    """Snapshot of visible fields with labels. Host-tolerant best effort:
    greenhouse/lever inputs carry ids or names; labels come from the
    wrapping .field-wrapper / label / aria-label."""
    fields: list[FormField] = []
    seen = set()
    inputs = frame.locator(
        "#application-form input:not([type=hidden]):not([type=submit]):not([type=button]), "
        "#application-form textarea, #application-form select")
    n = inputs.count()
    for i in range(n):
        el = inputs.nth(i)
        info = el.evaluate(
            """el => {
                const wrap = el.closest('.field-wrapper') ||
                             el.closest('.input-wrapper') || el.parentElement;
                const label = wrap ? wrap.querySelector('label') : null;
                let opts = [];
                if (el.tagName === 'SELECT') {
                    opts = [...el.options].map(o => o.textContent.trim());
                }
                if (el.classList.contains('iti__search-input') ||
                    el.closest('.iti__dropdown-content')) return null;
                return {
                    id: el.id || null, name: el.name || null,
                    type: el.type || el.tagName.toLowerCase(),
                    aria: el.getAttribute('aria-label'),
                    label: label ? label.textContent.trim() : null,
                    required: !!(el.required || el.hasAttribute('aria-required')),
                    options: opts,
                    isSelect: !!el.closest('.select__control'),
                };
            }""")
        if info is None:
            continue
        label = (info["label"] or info["aria"] or info["name"] or
                 info["id"] or "").strip()
        sel = f"#{info['id']}" if info["id"] else (
            f"[name=\"{info['name']}\"]" if info["name"] else None)
        if not sel or not label:
            continue
        key = (label, info["type"])
        if key in seen:
            continue
        seen.add(key)
        kind = info["type"].lower()
        if info.get("isSelect"):
            kind = "select"
        fields.append(FormField(
            label=label.rstrip("*").strip(), kind=kind,
            options=info["options"], required=info["required"],
            locator_id=sel))
    return fields


def fill_from_bank(frame, fields: list[FormField], bank: AnswersBank,
                   ask_callback) -> tuple[int, int]:
    """Fill fields from the bank; ask_callback for the unknowns.

    ask_callback(fields: list[FormField]) -> dict[label, answer].
    Returns (answered_from_bank, asked_of_human).
    """
    unknown = [f for f in fields
               if f.kind in ("text", "textarea", "select", "tel", "email")
               and bank.lookup(f.label) is None
               and not (f.kind == "select" and EEO_PAT.search(f.label))]
    human_answers = ask_callback(unknown) if unknown else {}

    from_bank = asked = 0
    for f in fields:
        if f.kind == "file":
            continue  # uploads handled by the resume step
        is_eeo = f.kind == "select" and EEO_PAT.search(f.label)
        entry = bank.lookup(f.label)
        answer = entry.answer if entry else human_answers.get(f.label)
        if not answer and is_eeo:
            answer = "DECLINE"  # toggle-driven auto-decline
        if not answer:
            continue
        if entry is None:
            if not is_eeo:
                asked += 1
                bank.learn(f.label, answer, f.kind)
        else:
            from_bank += 1
        try:
            loc = frame.locator(f.locator_id).first
            if is_eeo:
                # pick the least committal option (decline/no-answer)
                loc.click(timeout=5000)
                opts = frame.locator(".select__menu:visible .select__option")
                target = next((i for i in range(opts.count())
                               if DECLINE_PAT.search(opts.nth(i).inner_text())),
                              None)
                if target is None:
                    page.keyboard.press("Escape")
                    continue
                opts.nth(target).click(timeout=5000)
            elif f.kind == "checkbox":
                # answer "yes" checks it; decline/none-style labels get
                # checked (group-exit options); "no" leaves unchecked
                should_check = answer.strip().lower() in (
                    "yes", "y", "true", "1", "check") or bool(
                    DECLINE_PAT.search(f.label))
                if should_check:
                    loc.check(timeout=5000)
            elif f.kind == "select" and "location" in f.label.lower():
                # geo-typeahead: type, wait, pick the suggestion
                loc.click(timeout=5000)
                loc.type(answer.split(",")[0].strip(), delay=60)
                frame.page.wait_for_timeout(2500)
                # suggestions expand the typed city ("Mexico City, Ciudad de
                # México..."), so match on the typed prefix only
                frame.locator(".select__menu:visible .select__option",
                              has_text=answer.split(",")[0]).first.click(timeout=5000)
            elif f.kind == "select":
                loc.click(timeout=5000)
                frame.locator(".select__menu:visible .select__option",
                              has_text=answer).first.click(timeout=5000)
            else:
                loc.fill(answer, timeout=5000)
        except Exception as e:
            print(f"  fill failed [{f.label[:40]}]: {str(e)[:400]}")
    return from_bank, asked


def attach_resume(frame, page, resume_path) -> bool:
    """First file input backs the resume slot; later ones hang."""
    inputs = frame.locator("#application-form input[type=file]")
    for _ in range(20):
        if inputs.count():
            break
        page.wait_for_timeout(500)
    if not inputs.count():
        print("  resume: no file inputs appeared")
        return False
    inputs.nth(0).set_input_files(str(resume_path), timeout=10000)
    page.wait_for_timeout(2500)
    return True


def walk_and_fill(page, app_frame, resume_path, bank: AnswersBank,
                  ask_callback, dry_run: bool = False) -> str:
    """Multi-page fill loop. Returns a status string:
    'ready' (filled, human must submit), 'no-form', 'blocked'."""
    form = app_frame.locator("#application-form")
    if form.count() == 0:
        return "no-form"

    pages_walked = 0
    while True:
        pages_walked += 1
        # Conditional questions mount only after earlier fields are filled,
        # so re-discover until the field set stabilizes (bounded).
        prev_ids = set()
        from_bank = asked = 0
        for _ in range(4):
            fields = discover_fields(app_frame)
            new_ids = {f.locator_id for f in fields}
            from_bank, asked = fill_from_bank(app_frame, fields, bank,
                                              ask_callback)
            fields2 = discover_fields(app_frame)
            new_ids2 = {f.locator_id for f in fields2}
            if new_ids2 == new_ids or new_ids2 == prev_ids:
                fields = fields2
                break
            prev_ids = new_ids
        visible = fields
        log_fields = ", ".join(f.label[:30] for f in visible[:12])
        print(f"page {pages_walked}: {len(visible)} fields ({log_fields}...)")
        print(f"  bank={from_bank} asked={asked}")
        attach_resume(app_frame, page, resume_path)
        # remount race: the resume upload can re-render the form and reset
        # selects — re-assert bank values (never re-asking the human)
        page.wait_for_timeout(1500)
        fill_from_bank(app_frame, discover_fields(app_frame), bank,
                       lambda f: {})

        nxt = app_frame.locator(
            "#application-form button, #application-form input[type=button]"
        )
        submit_btn = None
        next_btn = None
        for i in range(nxt.count()):
            b = nxt.nth(i)
            text = (b.inner_text() or b.get_attribute("value") or "").strip()
            if SUBMIT_PAT.search(text) and "submit" in text.lower():
                submit_btn = b
                break
            if NEXT_PAT.search(text) and next_btn is None:
                next_btn = b
        if submit_btn is not None and not submit_btn.is_disabled():
            if dry_run:
                return "ready"
            print("  submit button enabled — stopping for HUMAN to submit")
            return "ready"
        if next_btn is not None:
            try:
                next_btn.click(timeout=8000)
                page.wait_for_timeout(2500)
                continue
            except Exception:
                pass
        if submit_btn is not None:
            # present but disabled: prerequisites missing (uploads, gates)
            return "blocked"
        return "blocked" if pages_walked > 1 else "no-submit"


def open_application(page, job_url: str, timeout_s: float = 30):
    """Navigate and locate the application frame, polling for SPA mounts."""
    page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)
    if "lever.co" in page.url and not page.url.rstrip("/").endswith("/apply"):
        page.goto(page.url.rstrip("/") + "/apply",
                  wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)

    deadline = time.time() + timeout_s
    app = find_app_frame(page)
    form = app.locator("#application-form")
    while form.count() == 0 and time.time() < deadline:
        for trigger in ["button:has-text('Apply')",
                        "a:has-text('Apply Now')",
                        "text=Apply Now"]:
            loc = page.locator(trigger)
            if loc.count():
                try:
                    loc.first.click(timeout=3000)
                    break
                except Exception:
                    continue
        page.wait_for_timeout(2000)
        app = find_app_frame(page)
        form = app.locator("#application-form")
    return (app, form) if form.count() else (None, None)


def drive_ashby(page, app, resume_path, bank: AnswersBank, ask_callback,
                dry_run: bool = False) -> str:
    """Ashby application forms: React SPA, UUID-named fields, hashed CSS
    classes, no <form> element. Radio groups live in fieldsets whose text
    is 'question * option1 option2 ...'. Human performs the final submit.
    """
    if app.locator("input[type=text], textarea").count() < 2:
        btn = page.locator("button:has-text('Apply')").first
        if btn.count():
            btn.click(timeout=8000)
            page.wait_for_timeout(4000)

    inputs = app.locator(
        "input:not([type=hidden]):not([type=radio]):not([type=checkbox])"
        ":not([type=file]):not([type=submit]), "
        "textarea:not([name='g-recaptcha-response'])")
    n = inputs.count()
    for i in range(n):
        el = inputs.nth(i)
        info = el.evaluate(
            """el => {
                if (el.classList.contains('iti__search-input')) return null;
                let q = null;
                let t = el;
                for (let k = 0; k < 6 && t; k++) {
                    t = t.parentElement;
                    if (!t) break;
                    const lbl = t.querySelector('label[for]');
                    if (lbl && lbl.textContent.trim().length > 1) {
                        q = lbl.textContent.trim(); break;
                    }
                }
                if (!q) {
                    let s = el;
                    for (let k = 0; k < 5 && s; k++) {
                        s = s.parentElement;
                        if (!s) break;
                        const cand = [...s.children].filter(
                            c => !c.contains(el) && c.innerText &&
                            c.innerText.trim().length > 3 &&
                            c.innerText.trim().length < 120);
                        if (cand.length) { q = cand[cand.length-1].innerText.trim(); break; }
                    }
                }
                return {name: el.name || null, type: el.type || null, q: q};
            }""")
        if info is None:
            continue
        name, ftype, q = info["name"], info["type"], info["q"] or ""
        if ftype == "email" or name == "_systemfield_email" or                 (q and "email" in q.lower()):
            entry = bank.lookup("email")
            val = entry.answer if entry else None
        elif name == "_systemfield_name":
            first = bank.lookup("first name")
            last = bank.lookup("last name")
            val = ((first.answer if first else "") + " " +
                   (last.answer if last else "")).strip()
        elif q and "location" in q.lower():
            entry = bank.lookup("location city")
            if not entry:
                continue
            el.click(timeout=5000)
            el.type(entry.answer.split(",")[0].strip(), delay=60)
            page.wait_for_timeout(2500)
            sug = app.locator("[class*='suggestion'], [role='option']")
            if sug.count():
                sug.first.click(timeout=5000)
            continue
        elif q and "github" in q.lower():
            entry = bank.lookup("website")
            val = entry.answer if entry else None
            if not val: continue
        else:
            entry = bank.lookup(q) if q else None
            if entry is None and q:
                entry = bank.lookup(_question_key(q))
            val = entry.answer if entry else None
            if not val and q:
                human = ask_callback([FormField(label=q, kind=ftype,
                                                locator_id="")])
                val = human.get(q)
            if not val:
                continue
        try:
            el.fill(val, timeout=5000)
        except Exception as e:
            print(f"  ashby fill failed [{name or q[:30]}]: {str(e)[:50]}")

    # Radio groups (fieldsets): question = first text line, options = rest.
    fieldsets = app.locator("fieldset")
    for i in range(fieldsets.count()):
        fs = fieldsets.nth(i)
        if fs.locator("input[type=radio]").count() == 0:
            continue
        lines = [l.strip() for l in fs.inner_text().split("\n") if l.strip()]
        if not lines:
            continue
        question = lines[0]
        options = [l for l in lines[1:] if len(l) > 1]
        entry = bank.lookup(question)
        answer = entry.answer if entry else None
        if not answer and EEO_PAT.search(question):
            answer = "DECLINE"
        if not answer and "sponsorship" in question.lower():
            entry = bank.lookup("sponsorship")
            answer = entry.answer if entry else None
        if not answer and "relocat" in question.lower():
            entry = bank.lookup("relocate")
            answer = entry.answer if entry else None
        if not answer and "clearance" in question.lower():
            entry = bank.lookup("clearance")
            answer = entry.answer if entry else None
        if not answer:
            human = ask_callback([FormField(label=question, kind="radio",
                                            options=options, locator_id="")])
            answer = human.get(question)
        if not answer:
            continue
        if answer == "DECLINE":
            pick = next((o for o in options if DECLINE_PAT.search(o)), None)
        else:
            pick = next((o for o in options
                         if o.lower() == answer.lower()
                         or answer.lower() in o.lower()), None)
        if pick is None:
            # parsed options can miss decline variants; try the DOM anyway
            fallback = fs.locator("label, [class*='option']",
                                  has_text=answer[:12]).last
            if fallback.count() == 0:
                print(f"  ashby radio: no option for '{answer[:30]}' in "
                      f"'{question[:40]}'")
                continue
            try:
                fallback.click(timeout=5000)
                print(f"  ashby radio (fallback): '{answer[:30]}' "
                      f"({question[:40]})")
            except Exception as e:
                print(f"  ashby radio failed [{question[:40]}]: {str(e)[:50]}")
            continue
        target = fs.locator("label, [class*='option']", has_text=pick).last
        try:
            target.click(timeout=5000)
            print(f"  ashby radio: '{pick[:30]}' ({question[:40]})")
        except Exception as e:
            print(f"  ashby radio failed [{question[:40]}]: {str(e)[:50]}")

    # Resume: first required file input.
    files = app.locator("input[type=file]")
    for i in range(files.count()):
        f = files.nth(i)
        required = f.evaluate(
            "el => !!el.required || !!el.getAttribute('aria-required')")
        if required:
            try:
                f.set_input_files(str(resume_path), timeout=10000)
                page.wait_for_timeout(2500)
                log("ashby resume attached")
            except Exception as e:
                log(f"ashby resume failed: {str(e)[:60]}")
            break

    return "ready"


def _question_key(q: str) -> str:
    """Cheap question normalization for bank fallback lookups."""
    q = q.lower().strip().rstrip("*?")
    if "sponsorship" in q: return "sponsorship"
    if "legally authorized" in q: return "legally authorized to work"
    if "clearance" in q or "top secret" in q: return "clearance"
    if "relocat" in q: return "relocate"
    if "years" in q and "experience" in q: return "industry experience"
    return q


def find_app_frame(page):
    return next((f for f in page.frames
                 if "greenhouse.io" in f.url
                 and ("job_app" in f.url or "jobs" in f.url)),
                page.main_frame)
