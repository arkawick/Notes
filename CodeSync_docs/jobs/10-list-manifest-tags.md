# list_manifest_tags

> **Sources:** 🎙 KT Sessions 3–4 · 🧭 proposed · ❓ unconfirmed. This job is not in the PPT or the older checkout.
> **Background:** [CodeSync_KT.md §11.3](../../CodeSync_KT.md#113-list_manifest_tags)

---

## 1. Job Identification

| Field | Value |
|---|---|
| **Job Name** | `list_manifest_tags` ❓ *exact name and whether there is one per product: confirm in Jenkins* |
| **Job URL** | Prod: `https://codesync.ptc.sony.co.jp/job/list_manifest_tags/` ❓ |
| **Category** | Utility |
| **Vendor / Source** | Qualcomm (CodeLinaro + Chipcode) and Sony review |
| **Component** | Kernel / QSSI / Vendor Techpack (per component) |
| **Criticality** | 🧭 **Normal** (read-only), but it is the **go/no-go gate** for every import |

## 2. Purpose / Job Description

**What does this job actually do?**
For each component, it lists the current tag on three sides:

| Side | Meaning |
|---|---|
| CodeLinaro | Tag available on CLO |
| Chipcode | Tag available on Chipcode |
| Sony | Tag currently on the Sony review-server ref branch |

**Why is this job required?**
🎙 **Only import when the new tag is present on BOTH CodeLinaro and Chipcode.** Importing a half-published release fails or imports incomplete content. **Kernel has no Chipcode entry**, so check CLO only (❓ reason unknown). It also shows the gap between the latest vendor tag and what Sony has.

## 3. Trigger Information

| Field | Value |
|---|---|
| **Trigger Type** | Manual ❓ (may also be scheduled; check *Configure*) |
| **Schedule** | ❓ |
| **Manual Trigger Allowed?** | Yes |
| **When to trigger manually** | When a release email arrives; right before triggering any `Import_Qcom_*`; to re-check after a failed import caused by missing tags |
| **Triggered by another job?** | No |
| **Downstream Jobs** | None (gates the human decision to run `Import_Qcom_*`) |

**Flow:** `Release email / QPM → list_manifest_tags → (CLO == Chipcode == new tag?) → Import_Qcom_*`

## 4. Job Parameters

> 📷 **Screenshot:** _add "Build with Parameters" and a sample output_ → `../images/list-manifest-tags-params.png`, `../images/list-manifest-tags-output.png`

| Parameter | Mandatory? | Example | Description | How to determine value | Risk if wrong |
|---|---|---|---|---|---|
| ❓ (product / distro / component) | ❓ | ❓ | Not covered in the sessions | Fill in from the job's *Build with Parameters* page | Reading tags for the wrong product means a wrong go/no-go decision |

## 5. Expected Output

- A table per component: **CLO tag / Chipcode tag / Sony tag**
- No changes to any repository (read-only)

## 6. Output Validation / Success Criteria (Mandatory)

### Level 1: Jenkins
- **SUCCESS**. The output lists every expected component.

### Level 2: Git / Mirror
Cross-check one value by hand:
```bash
git ls-remote --tags <CLO manifest URL> | grep <expected AU tag suffix>
git ls-remote --tags git://review.ptc.sony.co.jp/platform/<kernel|qssi|target>manifest | tail
```

### Level 3: Manifest
The **Sony** column should equal the tag in `default.xml` on the component's `REF_BRANCH`.

### Level 4: Sync validation
N/A (read-only).

**Decision rule:** QSSI and Vendor: proceed only if CLO **and** Chipcode both show the new tag. Kernel: CLO only. Also compare against the release note and the published clone command (last 3 digits of the release number = tag suffix).

## 7. Failure & Troubleshooting History

| Date | Error / Symptom | Root Cause | Identification | Fix / Recovery | Jira | Preventive Action |
|---|---|---|---|---|---|---|
| ❓ | CLO and Chipcode disagree | Qualcomm publishing in stages | Output | **Wait** and rerun later. Do not import. | — | — |
| ❓ | Chipcode column empty for kernel | By design (Qualcomm never added kernel support there) | Output | Use CLO only | — | — |

## 8. Recovery / Rerun Procedure

**Is rerun safe?** **Yes.** It is read-only.

**Before rerun check:** upstream reachable (`git ls-remote`)? Credentials valid (all jobs run as `jp21771`)? Nothing else needed.

**Rerun steps:** *Build Now*.
