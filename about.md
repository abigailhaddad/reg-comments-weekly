# How this is made

Which Regulations.gov dockets drew public comments each week, counted from the [spicy-regs](https://github.com/civictechdc/spicy-regs) mirror of regulations.gov.

- Data: [spicy-regs mirror](https://github.com/civictechdc/spicy-regs)
- Selection: [selection rules](https://github.com/abigailhaddad/reg-comments-weekly/blob/main/config/reg-comments-weekly.yaml), applied in [report.py](https://github.com/abigailhaddad/reg-comments-weekly/blob/main/src/report.py)
- Claude: [prompts and settings](https://github.com/abigailhaddad/reg-comments-weekly/blob/main/config/reg-comments-weekly.yaml) (opening paragraph and sampled summaries)
- Checks: [opening.py](https://github.com/abigailhaddad/reg-comments-weekly/blob/main/src/opening.py), [mirror vs. API](https://github.com/abigailhaddad/reg-comments-weekly/tree/main/proof)
