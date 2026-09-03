"""Workable application-form adapter (apply.workable.com/{sub}/j/{id}).

Structure (Workable's React form): fields carry `name` attributes
(candidate name/email/phone/location via system fields, questions by id),
resume via file input, EEO section optional. STATUS: built against
Workable's documented form contract — live validation pending a real
Workable job token (see PENDING.md, discovery blocked on search access).
"""
import re

from .answers import AnswersBank
from .driver import FormField


def drive_workable(page, resume_path, bank: AnswersBank, ask_callback,
                   dry_run: bool = False) -> str:
    form = page.locator("form, [class*='application']").first
    form.wait_for(state="visible", timeout=30000)

    inputs = page.locator(
        "input:not([type=hidden]):not([type=radio]):not([type=checkbox])"
        ":not([type=file]):not([type=submit]), textarea")
    n = inputs.count()
    for i in range(n):
        el = inputs.nth(i)
        info = el.evaluate(
            """el => {
                let q = null;
                const lbl = el.closest('div')?.querySelector('label') ||
                            document.querySelector(`label[for='${el.id}']`);
                if (lbl) q = lbl.textContent.trim();
                if (!q && el.placeholder && el.placeholder !== 'Type here...')
                    q = el.placeholder;
                return {name: el.name || null, type: el.type || null, q: q};
            }""")
        name, val = info["name"], None
        nl = (info["q"] or "").lower()
        if "email" in nl or "email" in name:
            entry = bank.lookup("email")
            val = entry.answer if entry else None
        elif "first name" in nl or "first name" in name:
            entry = bank.lookup("first name")
            val = entry.answer if entry else None
        elif "last name" in nl or "last name" in name or "surname" in nl:
            entry = bank.lookup("last name")
            val = entry.answer if entry else None
        elif "phone" in nl or "phone" in name:
            entry = bank.lookup("phone number")
            val = entry.answer if entry else None
        elif "location" in nl or "location" in name:
            entry = bank.lookup("location city")
            val = entry.answer if entry else None
        elif "linkedin" in nl:
            entry = bank.lookup("linkedin profile")
            val = entry.answer if entry else None
        elif "github" in nl or "website" in nl:
            entry = bank.lookup("website")
            val = entry.answer if entry else None
        else:
            entry = bank.lookup(info["q"] or name or "")
            val = entry.answer if entry else None
            if not val:
                human = ask_callback([FormField(label=info["q"] or name or "?",
                                                kind=info["type"],
                                                locator_id="")])
                val = human.get(info["q"] or name or "?")
        if val:
            try:
                el.fill(val, timeout=5000)
            except Exception as e:
                print(f"  workable fill failed [{name or nl[:30]}]: "
                      f"{str(e)[:50]}")

    # Radio groups + selects by question text.
    radios = page.locator("input[type=radio]")
    seen = set()
    for i in range(radios.count()):
        r = radios.nth(i)
        nm = r.get_attribute("name") or ""
        if nm in seen:
            continue
        seen.add(nm)
        q = r.evaluate(
            """el => {
                let t = el;
                for (let k = 0; k < 6 && t; k++) {
                    t = t.parentElement;
                    if (!t) break;
                    const lbl = t.querySelector('label');
                    if (lbl && lbl.innerText.trim().length > 3 &&
                        !el.closest('label').contains(lbl))
                        return lbl.innerText.trim();
                }
                return null;
            }""")
        if not q:
            continue
        entry = bank.lookup(q)
        answer = entry.answer if entry else None
        if not answer:
            human = ask_callback([FormField(label=q, kind="radio",
                                            locator_id="")])
            answer = human.get(q)
        if not answer:
            continue
        opt = r.locator(
            "xpath=ancestor::div[1]//label[contains(translate(., "
            "'YESNO', 'yesno'), '" +
            ("yes" if answer.lower().startswith("yes") else "no") + "')]").first
        try:
            opt.click(timeout=5000)
        except Exception as e:
            print(f"  workable radio failed [{q[:40]}]: {str(e)[:50]}")

    # Resume: first file input.
    files = page.locator("input[type=file]")
    if files.count():
        try:
            files.nth(0).set_input_files(str(resume_path), timeout=10000)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"  workable resume failed: {str(e)[:60]}")

    return "ready"

