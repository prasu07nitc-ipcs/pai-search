# Contact

Follow the shared policies in [../AGENTS.md](../AGENTS.md) and the runtime contract
in [../README.md](../README.md). Keep contact-specific behavior in this folder.

## Usage

From pai-search/, run:

```sh
forms/.venv/bin/python -B forms/runner.py --form form-contact
```

Open the printed localhost URL. Initial values may be supplied in the URL fragment,
for example `/new/form-contact#%7B%22name%22%3A%22Jane%22%7D`.

## Fields and validation

All fields are strings; preserve formatting and incomplete draft input.

- `name`: required, nonempty after trimming; input limit 200 characters.
- `email_id`: required; basic email syntax; input limit 320 characters.
- `phone_number`: required; 7–15 digits with optional leading plus sign, spaces,
  parentheses, periods, and hyphens; input limit 40 characters.
- `upi_id`: optional; basic `name@bank` syntax; input limit 200 characters.

Validation checks syntax only, not ownership, deliverability, or payment eligibility.

## Actions and output

Header Save button (`save_draft`) saves the complete snapshot without submission validation.
Submit details (`submit`) validates the fields, records an accepted action, and
freezes the session only when accepted. The saved envelope's
`meta_data.current_data` contains `name`, `email_id`, `phone_number`, and `upi_id`.
The shared runtime preserves initial data and action history.

No email, SMS, payment, or other external request is made. UPI ID is collected as
text only. Session files and logs contain personal data; use temporary directories
for tests and never print or commit production records.

Validation errors appear inside the affected field border without replacing values.
Any subsequent form interaction or 60 seconds clears the errors. Invalid browser
submissions are not persisted; save draft bypasses validation.
