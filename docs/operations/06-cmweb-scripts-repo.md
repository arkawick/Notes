# 06 — The `cmweb-scripts` repository

The third repository. It contains **no application code** — it is the AWS
infrastructure, the server configuration, the Jenkins job definitions, and the
git-mirroring machinery that keeps CMWEB's database fed.

It has its own release cycle and its own review branch (`cloudj2`), which is
why it is a separate repository rather than a directory inside the application.

---

## 1. Map

```
cmweb-scripts/                                          files
├── cloudformation/     AWS resources: EC2 Image Builder, IAM, VPC     21
├── agent/              Packer + Ansible for the Jenkins slave AMI      8
├── ansible/            Web-server configuration (11 roles)            56
├── jobs_on_cloud/      Jenkins Job Builder YAML (47 jobs)             54
├── bin/                Mirroring and command-runner scripts            6
├── etc/                Mirror rules, pip requirements                  4
├── configurator/       git submodule (empty here)                      0
├── .gitmodules
├── .gitattributes
└── .gitignore
```

Two of these have their own chapter:

| Directory | Chapter |
| --- | --- |
| `ansible/` | [04 — Ansible playbooks](04-ansible-playbooks.md) |
| `jobs_on_cloud/` | [03 — Jenkins jobs (JJB)](03-jenkins-jobs.md) |
| `ansible/roles/apache-server/` | [05 — Apache configuration](05-apache-config.md) |

This document covers everything else, and how the pieces connect.

---

## 2. Repository metadata

### `.gitmodules` — the empty directory

```ini
[submodule "configurator"]
	path = configurator
	url = git://review-plus.ptc.sony.co.jp/jenkins-jobs-configurator
	branch = master
```

`configurator/` is a **git submodule**, not a real directory. In this extracted
working copy it is empty, but `jobs_on_cloud/Makefile` depends on it:

```make
include ../configurator/Makefile
```

So `make update` in `jobs_on_cloud/` cannot work without
`git submodule init && git submodule update` — which is exactly what the
`get-scripts` Image Builder component does (section 3.2) and what the
`cmweb-checkout-scripts` Jenkins builder does (`git clone … --recursive`).

**If a JJB make target fails with "no rule to make target", the submodule is not
checked out.**

### `.gitattributes` — readable vault diffs

```
ansible/encrypted_vars/* diff=ansible-vault merge=binary
```

Two effects:

- `diff=ansible-vault` lets `git diff` show **plaintext** for encrypted files,
  once you configure the textconv driver locally:

```bash
git config diff.ansible-vault.textconv "ansible-vault view --vault-password-file=.vault"
```

- `merge=binary` prevents git from attempting a line-based merge on ciphertext,
  which would produce an unopenable file. Conflicts must be resolved by
  decrypting both sides.

### `.gitignore`

```
.project .pydevproject .settings      # Eclipse/PyDev
.key .vault_password .vault           # secrets used locally
all.retry                             # Ansible retry files
```

The three secret files are the ones you create by hand to run Ansible or
`ansible-vault` locally. **They are gitignored, not absent by accident** —
never commit one.

---

## 3. `cloudformation/` — the AWS foundation

21 files defining everything that exists in AWS before any server does.

```
cloudformation/
├── README
├── upload_all.sh            push templates to S3
├── create-stack.sh          create a stack from an uploaded template
├── create-change-set.sh     update an existing stack
├── validate-template.sh
├── ec2imagebuilder/         9 templates — the web-server AMI pipeline
├── iam/                     3 instance profiles
└── vpc/                     3 security groups
```

### 3.1 Workflow

From the `README`:

```bash
# 1. Upload templates to S3
./upload_all.sh

# 2-1. Stack already exists -> change set, then execute it in the console
./create-change-set.sh PATH/TO/ROOT_TEMPLATE.yaml

# 2-2. No stack yet -> create
./create-stack.sh PATH/TO/ROOT_TEMPLATE.yaml
```

Templates are **nested**: a root template references children by S3 URL, so all
of them must be uploaded before any stack operation. That is why `upload_all.sh`
is step 1 and not optional.

`create-stack.sh` uses the same account-id discovery as everything else:

```bash
ACCOUNT_ID=`curl -s http://169.254.169.254/latest/meta-data/identity-credentials/ec2/info/ | jq -r ".AccountId"`
if   [ "659398199407" = "${ACCOUNT_ID}" ] ; then ENV="prod"
elif [ "009896685360" = "${ACCOUNT_ID}" ] ; then ENV="stage"
elif [ "100267242497" = "${ACCOUNT_ID}" ] ; then ENV="test"
else
  echo "Error: Something wrong : ACCOUNT_ID="${ACCOUNT_ID}
  exit 1
fi

BACKET=${ACCOUNT_ID}-ap-northeast-1-cmweb-cloudformation-templates
STACK=${FILE_NAME%.*}

aws cloudformation create-stack \
  --stack-name ${STACK} \
  --template-url ${URL} \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM

aws cloudformation wait stack-create-complete --stack-name ${STACK}
```

**The stack name is the filename.** Rename a template and you create a second
stack rather than updating the first.

These scripts are run *on an EC2 instance*, not from a laptop — they read the
instance metadata service to decide which environment they are in.

### 3.2 `ec2imagebuilder/` — how the web AMI is built

Nine templates, composed:

```
builder-cmweb-pipeline.yaml          ImagePipeline (x2: ubuntu20, ubuntu22)
   ├── builder-cmweb-infra-release.yaml     InfrastructureConfiguration
   ├── builder-cmweb-recipe.yaml            ImageRecipe (x2)
   │      ├── component-setup-proxy
   │      ├── component-get-tools
   │      ├── component-setup-password
   │      ├── component-get-scripts
   │      ├── component-provision-web
   │      └── component-teardown-password
   └── builder-cmweb-distribution.yaml      DistributionConfiguration
```

**The six components run in this exact order**, and the order is the story:

| # | Component | Does |
| --- | --- | --- |
| 1 | `setup-proxy` | Writes `/etc/apt/apt.conf.d/80proxy` pointing at `proxy-sen.noc.sony.co.jp:10080` — **nothing can apt-get before this** |
| 2 | `get-tools` | `apt-get update && upgrade`, then installs `awscli`, `jq`, `ansible` |
| 3 | `setup-password` | Pulls the Ansible vault password from Secrets Manager to `~/.vault`, mode 400 |
| 4 | `get-scripts` | SSH key from Secrets Manager, git config, `git clone cmweb-scripts`, `git checkout cloudj2`, submodule init/update |
| 5 | `provision-web` | **`ansible-playbook -c local -i hosts/$ENV web-servers.yml`** |
| 6 | `teardown-password` | `rm ~/.vault` |

Two things worth dwelling on.

**Secrets never land in the image.** Component 3 fetches the vault password,
component 5 uses it, component 6 deletes it — all before the AMI snapshot. Same
pattern for the SSH key, which is written by component 4:

```bash
mkdir -p ~/.ssh
aws configure set default.region ap-northeast-1
aws secretsmanager get-secret-value --secret-id cmweb/ssh/ed25519 \
  | jq -r .SecretString | jq -r .id_ed25519 > ~/.ssh/id_ed25519
chmod 400 ~/.ssh/id_ed25519
```

...though note the SSH key is **not** torn down, only the vault password.

**The git URL rewrite** in component 4 is what lets the Ansible roles use
`git://` URLs that actually go over authenticated SSH:

```bash
echo '[url "ssh://jp21602@git-plus-jdc.ptc.sony.co.jp:29418/"]' >> ~/.gitconfig
echo '  insteadOf = git://review-plus.ptc.sony.co.jp/' >> ~/.gitconfig
```

So every `repo init -u git://review-plus.ptc.sony.co.jp/cmweb-manifest` in the
Ansible roles silently becomes an SSH fetch as the service account.

#### The recipe

```yaml
  BuilderRecipeWebUbuntu22:
    Type: AWS::ImageBuilder::ImageRecipe
    Properties:
      Components: [ Proxy, Tools, SetupPass, Scripts, Web, TeardownPass ]
      Name: cmweb-on-ubuntu22
      ParentImage: arn:aws:imagebuilder:ap-northeast-1:aws:image/ubuntu-server-22-lts-x86/x.x.x
      Version: 0.0.1
```

Two recipes, one per Ubuntu LTS — the reason `cmweb-project/etc/` carries both
`requirements-20.txt` and `requirements-22.txt`, and why the `package` Ansible
role has `vars/focal.yml` and `vars/jammy.yml`.

`ParentImage` uses `x.x.x`, so each build takes the **latest** AWS-managed
Ubuntu image. Combined with `apt-get upgrade` in component 2 and
`upgrade: true` in the Ansible `package` role, **AMI builds are not
reproducible**: the same commit built a week apart gives a different image.

#### Infrastructure configuration

```yaml
Mappings:
  Network:
    "659398199407": { Env: "prod",  Subnet: "subnet-09e6...", SG: "sg-0bb2..." }
    "009896685360": { Env: "stage", Subnet: "subnet-0d7a...", SG: "sg-070e..." }
    "100267242497": { Env: "test",  Subnet: "subnet-005b...", SG: "sg-0d6c..." }

Resources:
  BuilderInfraRelease:
    Properties:
      Description: stop instance if fail
      InstanceProfileName: profile-cmweb-ec2-image-builder
      InstanceTypes: [ t3a.small ]
      SecurityGroupIds: [ !FindInMap [ Network, !Ref "AWS::AccountId", SG ] ]
      SubnetId:          !FindInMap [ Network, !Ref "AWS::AccountId", Subnet ]
      Logging:
        S3Logs: { S3BucketName: !Sub '${AWS::AccountId}-ap-northeast-1-cmweb' }
      SnsTopicArn: !Sub 'arn:aws:sns:ap-northeast-1:${AWS::AccountId}:cmweb-sns'
```

`!FindInMap` on `AWS::AccountId` is the CloudFormation equivalent of the
account-id `if` chain in the shell scripts — **the same environment-detection
idea expressed three different ways across this repository** (shell in
`create-stack.sh` and `provision-web`, `FindInMap` here, `JENKINS_URL`
comparison in `macros.yaml` and `run_commands.sh`).

`Description: stop instance if fail` means a failed build leaves the instance
running for inspection rather than terminating it. **Check for orphaned
`t3a.small` instances after a failed image build.**

#### Distribution

```yaml
  BuilderDistro:
    Properties:
      Name: ami
      Distributions:
        - AmiDistributionConfiguration:
            AmiTags: { System: cmweb, Name: cmweb-web }
          Region: ap-northeast-1
```

Single region, tagged `System: cmweb` / `Name: cmweb-web`. Those tags are how
you find the AMI to launch from.

### 3.3 `iam/` — three instance profiles

| Template | Profile | For |
| --- | --- | --- |
| `profile-cmweb-web.yaml` | `profile-cmweb-web` | The web servers |
| `profile-cmweb-jenkins.yaml` | `profile-cmweb-jenkins` | The Jenkins slaves |
| `profile-cmweb-ec2-image-builder.yaml` | `profile-cmweb-ec2-image-builder` | The AMI build instances |

The web profile:

```yaml
      Path: "/cmweb/"
      ManagedPolicyArns:
        - "arn:aws:iam::aws:policy/AmazonS3FullAccess"
        - "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
```

`AmazonSSMManagedInstanceCore` is what allows Session Manager access without
opening SSH. `AmazonS3FullAccess` is an AWS-managed blanket policy — broader
than this role needs, and the obvious candidate if anyone tightens IAM here.

### 3.4 `vpc/` — three security groups

`sg-cmweb-rds.yaml`, `sg-cmweb-elasticache.yaml`, `sg-cmweb-all-testenv.yaml` —
the PostgreSQL and memcached ingress rules, plus a permissive test-environment
group.

---

## 4. `agent/` — the Jenkins slave AMI

A **separate** AMI lineage from the web servers, built with **Packer** rather
than EC2 Image Builder.

```
agent/
├── agent.yml                      the Ansible playbook
├── agent18.pkrvars.hcl            Packer vars, Ubuntu 18.04 (bionic)
├── agent20.pkrvars.hcl            Packer vars, Ubuntu 20.04 (focal)
├── resources/python/3.8/
│   ├── requirements.txt           ansible==2.9.27
│   └── requirements.lock
└── roles/packages/
    ├── tasks/main.yml
    └── vars/{bionic,focal}.yml
```

```hcl
project_name       = "cmweb-agent-focal"
os_name            = "Ubuntu 20.04"
ssm_parameter_name = "/ubuntu/focal/cmeb/agent"
ami_name           = "jenkins-slave-focal-*"
playbook           = "project/agent.yml"
subnet_tag         = "logic-ap-northeast-1a"
kms_key_id         = "alias/amibuild"
encrypt_boot       = true
tag_system         = "cmweb"
```

The playbook is trivial — one role, one job:

```yaml
- hosts: default
  become: true
  vars:
    ansible_python_interpreter: /usr/bin/python3
  roles:
    - packages
```

```yaml
required_packages:
  - libpq5, libpq-dev              # PostgreSQL client headers (psycopg2)
  - unixodbc, unixodbc-dev         # ODBC (dmsclient)
  - libcurl4-openssl-dev
  - graphviz, libgraphviz-dev, pkg-config   # django-extensions graph_models
  - libxml2-dev, libxslt1-dev      # lxml
  - memcached
  - libssl-dev
  - libldap2-dev, libsasl2-dev     # python-ldap
  - nfs-common                     # EFS mount
```

**This list is the build-dependency set for CMWEB's Python packages.** Every
entry maps to a C extension that `make install` compiles on the slave. If a
Jenkins job starts failing at `make install` with a missing header, this file is
where the fix goes — not `requirements.txt`.

Note `ssm_parameter_name = "/ubuntu/focal/cmeb/agent"` — **"cmeb" is a typo for
"cmweb"**, baked into the SSM parameter path. Harmless as long as nothing
changes, but worth knowing when searching Parameter Store.

Two `pkrvars` files, bionic and focal, while `defaults.yaml` in `jobs_on_cloud`
pins `node: 'CMWEB_SLAVE_22'` — a Ubuntu **22** label with no matching agent
definition here. The 22.04 agent is evidently built elsewhere or the vars file
was never added; either way the agent definitions in this directory are behind
the node label the jobs actually request.

---

## 5. `bin/` — the scripts

Six files. Two are called by Jenkins jobs, three by the mirroring job, one is a
guard.

### 5.1 `run_commands.sh` — the standalone command runner

Covered in [03 §8](03-jenkins-jobs.md). It is the script equivalent of the
`cmweb-generate-settings` + `cmweb-run-commands` builders: pick hosts by
`JENKINS_URL`, sync the mirror, `repo init`/`repo sync`, write `secure.py` and
`settings_management.py`, `make install`, then:

```bash
echo $COMMANDS | tr ";" "\n" | while read line; do
  echo "---- Executing $line"
  ./manage.py $line -v3 --traceback || { echo "$line" >> failed_commands ; }
done
exit `wc -l < failed_commands`
```

It also explicitly re-asserts `CELERY_TASK_ALWAYS_EAGER = True`.

### 5.2 `repo_sync_projects.sh` — the indexing checkout

Called three times in a row by `run_commands.sh` (`A || A || A`) because it is
the flakiest step.

```bash
if [ -n "$REPO_MIRROR" -a -n "$REPO_MANIFEST" -a -n "$REPO_BRANCH" ] ; then
  if [ "$REPO_MIRROR_UPDATE_FIRST" == "true" ] ; then
    cd $REPO_MIRROR
    rm -rf .repo
    repo init -u $GERRIT_SERVER/$REPO_MANIFEST -b $REPO_BRANCH --no-repo-verify --mirror
    repo sync -j4
  fi
  if [ "$REPO_SKIP_CHECKOUT" == "true" ] ; then exit ; fi
  mkdir -p $HOME/.cmweb/indexing-repo
  rm repo-checkout
  ln -s $HOME/.cmweb/indexing-repo repo-checkout
  cd $HOME/.cmweb/indexing-repo
  rm -rf * .repo
  repo init -u $REPO_MIRROR/$REPO_MANIFEST.git -b $REPO_BRANCH --reference=$REPO_MIRROR --no-repo-verify
  repo sync -d -j4 -c $REPO_SYNC_PROJECTS
else
  echo "Not syncing projects: ..."
fi
```

Four environment variables control it — `REPO_MIRROR`, `REPO_MANIFEST`,
`REPO_BRANCH`, plus optional `REPO_MIRROR_UPDATE_FIRST`, `REPO_SKIP_CHECKOUT`,
`REPO_SYNC_PROJECTS`. **If any of the first three is unset, the script does
nothing and exits 0** — it prints the "Not syncing projects" message and
succeeds. A silent no-op is easy to miss in a build log.

`--reference=$REPO_MIRROR` makes the working checkout share objects with the
mirror instead of re-fetching them.

### 5.3 `mirror_repo.sh` + `manifest.py` + `mirror-creator.jar`

The git-mirroring trio, and the most interesting loop in the repository.

```bash
magic_mirror_tag=MAGIC-MIRROR-ALL-EVERYTHING
manifest_server=https://${SERVICE_USERNAME}:${SERVICE_PASSWORD}@cmweb.ptc.sony.co.jp/rpc

cd $REPO_MIRROR

# Get hold of the magic mirror manifest and generate a project.list
python $here/manifest.py $manifest_server $magic_mirror_tag
grep -e '<project' mirrormanifest.xml | \
  grep -o -e 'name="[^"]*"' | sed -e 's/name="//g' -e 's/"//g' > project.list

# Remove any failed gits, in the hope that it would be successful this time
rm -rf `cat .mirror-update-logs/mirror_creation_stats.csv | grep false | \
  tr ';' ' ' | awk '{ print $2; }'`

for p in `cat project.list` ; do echo "^$p\$" ; done | sort > whitelist.txt.tmp
java -jar $here/mirror-creator.jar \
  --slave --log-level vv --git-gc-auto 0 \
  --whitelist-src file://`pwd`/whitelist.txt.tmp \
  --whitelist-dst whitelist.txt \
  --mirror-location `pwd` \
  --fetch-notes \
  --backup-location `pwd -P`/../repo-mirror.backup/.repo-mirror.backup \
  --gerrit-host review.ptc.sony.co.jp \
  --gerrit-command-host review.ptc.sony.co.jp \
  --gerrit-command-port 29418 \
  --gerrit-username jp21602
```

**`manifest.py` calls CMWEB's own XML-RPC endpoint:**

```python
server = xmlrpc.client.Server(manifest_server)
[success, manifest_str] = server.GetManifest(manifest_label)
```

So the mirroring script asks **the website** which repositories to mirror, then
mirrors them so that the indexer can populate the website. That is why `/rpc/`
is one of the four anonymous paths in the Apache vhost
([05 §2](05-apache-config.md)) and one of the entries in `NO_AUTH_URLS` — it
exists to serve this script.

Other details:

- `--fetch-notes` is what brings `refs/notes/review` across, which is where
  `sync_commits` reads approvers, verifiers and review scores from. **Without
  it, commit review metadata would be empty.**
- `--git-gc-auto 0` disables automatic gc during mirroring.
- The `rm -rf` line deletes every repository that the previous run recorded as
  `false` in `mirror_creation_stats.csv`, so a half-fetched repo is retried
  cleanly. It is an unquoted backtick expansion feeding `rm -rf` — safe only
  because the CSV is machine-generated.

Note this script mirrors from **`review.ptc.sony.co.jp`** (Gerrit) while the
code is fetched from **`review-plus.ptc.sony.co.jp`** (Gerrit Plus). Two
different servers; do not conflate them.

The `mirror_gits` Jenkins job does **not** call this script — it runs
`repo sync -t MAGIC-MIRROR-ALL-EVERYTHING` directly against
`git://review.ptc.sony.co.jp/mirror/manifest`. `mirror_repo.sh` is the older or
alternative path using the Java mirror-creator.

### 5.4 `parameter_validation.sh` — the guard

A pure-bash sanity check that a triggered indexing job's `$BRANCH` and
`$MANIFEST` agree with the upstream `$JENKINS_PARENT_JOB_URL`:

```bash
elif [[ $JENKINS_PARENT_JOB_URL =~ "system" ]]; then
    if [[ $MANIFEST =~ "systemmanifest" ]]; then
        if [[ $JENKINS_PARENT_JOB_URL != *"${BRANCH}_"* ]]; then
            echo "Parameter mismatch: \$JENKINS_PARENT_JOB_URL & \$BRANCH do not match. Cannot proceed."
            exit 1
```

It handles `systemmanifest`, `amssmanifest`, `targetmanifest` and
`qssimanifest`, and skips the check entirely for CMWEB's own sync jobs and for
ODM branches, whose offbuild job naming convention differs.

**This exists because a build job triggering CMWEB with the wrong
branch/manifest pair would index a build into the wrong branch** — a data
corruption that is tedious to unpick. Failing the job early is cheaper.

---

## 6. `etc/` — rules and requirements

### `mirror-repo-rules.txt` (11 lines) — what gets mirrored

```
^platform/     ^semcapps/     ^semctools/     ^tools/     ^ia/
^quic/         ^douglascrockford     ^vendor/qcom
^mozilla-b2g/  ^releases/l10n/       ^devworld/
```

### `mirror-repo-rules-prio.txt` (26 lines) — what gets mirrored *first*

```
^platform/manifest              ^platform/compositionmanifest
^platform/amssmanifest          ^platform/systemmanifest
^platform/vendor/semc/          ^platform/vendor/sony/
^kernel                         ^device/
^product/common                 ^hardware/
^platform/frameworks/           ^platform/vendor/qcom
^platform/hardware/             ^platform/amss
^platform/boot                  ...
```

The manifests come first, deliberately: the indexer cannot resolve a build at
all until the manifest repository containing its revision is present. Everything
else can arrive later.

### `requirements.txt`

```
celery  django  six  python-json-logger
somc-django-inlines  repo-manifest  rpc4django
django-reversion  commit-message-checker  django-rest-swagger
```

Unpinned, and a much shorter list than
`cmweb-project/etc/requirements-22.txt`. This is the set of packages
**`cmweb-scripts`' own tooling** needs, not the application's — note four of
them (`somc-django-inlines`, `repo-manifest`, `commit-message-checker`,
`rpc4django`) are exactly the Sony-internal packages `local-cmweb/stubs/` has
to stand in for.

### `requirements_deploy_jenkins_jobs.txt`

```
wheel
pbr==5.11.1
python-jenkins==1.3.0
PyYAML==6.0.2
jenkins-job-builder>=3.10.0
six>=1.9.0 # MIT
stevedore==1.17.1 # Apache-2.0
argparse
requests>=2.22
```

Installed by the `cmweb-prepare-jjb` builder. Tightly pinned, because JJB is
notoriously sensitive to `python-jenkins` and `stevedore` versions.

---

## 7. The three AWS accounts

Every environment-detection mechanism in the repository resolves to this table:

| Account ID | Env | Hostname | RDS | Jenkins |
| --- | --- | --- | --- | --- |
| `659398199407` | prod | `cmweb.ptc.sony.co.jp` | `cmweb.cm8tmtafyb32…` | `ci-tools.ptc.sony.co.jp` |
| `009896685360` | stage | `cmweb.ptc-stage.sony.co.jp` | `cmweb.cl0tidynvdpp…` | `ci-tools.ptc-stage.sony.co.jp` |
| `100267242497` | test | `cmweb.ptc-test.sony.co.jp` | `cmweb.cbes5fhcsnrc…` | none |

And it is expressed **four different ways** in four places:

| Mechanism | Where |
| --- | --- |
| `curl` IMDS + `if` chain on account id | `cloudformation/create-stack.sh`, `component-provision-web` |
| CloudFormation `!FindInMap` on `AWS::AccountId` | `builder-cmweb-infra-release.yaml` |
| `if` chain on `$JENKINS_URL` | `jobs_on_cloud/macros.yaml`, `bin/run_commands.sh` |
| Ansible `group_vars/<env>` selected by inventory | `ansible/hosts/{prod,stage,test}` |

> **These are not cross-checked against each other.** The stage RDS hostname
> appears in `ansible/group_vars/stage` *and* in `macros.yaml` *and* in
> `run_commands.sh`, with nothing enforcing agreement. Changing an endpoint
> means grepping for it, not editing one file.

---

## 8. How it all fits together

Two independent AMI lineages, and the runtime loop between them:

```
      ┌──────────────── build time ────────────────┐

  EC2 Image Builder                        Packer
  (cloudformation/ec2imagebuilder)         (agent/)
         │                                    │
         │ 6 components                       │ ansible: packages role
         │ └─ provision-web                   │
         │     └─ ansible-playbook            │
         │         web-servers.yml            │
         ▼                                    ▼
   AMI: cmweb-web                      AMI: jenkins-slave-*
         │                                    │
      ┌──┴──────────── run time ──────────────┴──┐
      ▼                                          ▼
  Web servers                              Jenkins slaves
  Apache + mod_wsgi                        jobs_on_cloud/*.yaml
  16 × 15 workers                          └─ bin/run_commands.sh
      │                                        └─ manage.py <command>
      │                                            │
      │         ┌──────────────────┐               │
      └────────►│   RDS PostgreSQL │◄──────────────┘
                └──────────────────┘
                         ▲
                         │ reads
                 ┌───────┴────────┐
                 │  EFS git mirror│◄── mirror_gits job
                 └────────────────┘        (bin/mirror_repo.sh,
                                            manifest.py → /rpc)
```

The loop worth noticing: **the mirroring script asks the website which
repositories to mirror** (`manifest.py` → `/rpc`), the mirror feeds the
indexers, and the indexers populate the website.

---

## 9. Where to change what

| To change | Edit | Then |
| --- | --- | --- |
| Apache vhost | `ansible/roles/apache-server/templates/apache/cmweb.conf.j2` | Rebuild the AMI, or run the playbook |
| A server package | `ansible/roles/package/vars/<release>.yml` | Rebuild the AMI |
| A Jenkins-slave build dependency | `agent/roles/packages/vars/<release>.yml` | Rebuild the agent AMI with Packer |
| A per-environment endpoint | `ansible/group_vars/<env>` **and** `jobs_on_cloud/macros.yaml` **and** `bin/run_commands.sh` | Grep — they are not linked |
| A secret | `ansible-vault edit ansible/encrypted_vars/*.yml` | Rebuild the AMI |
| A Jenkins job or schedule | `jobs_on_cloud/<verb>_<thing>.yaml` | Merge — `deploy_jenkins_jobs` fires on Gerrit ref-update |
| Which repos get mirrored | `etc/mirror-repo-rules*.txt` | Next `mirror_gits` run |
| An AWS resource | `cloudformation/**/*.yaml` | `./upload_all.sh` then `./create-change-set.sh` |
| The Ubuntu base image | `cloudformation/ec2imagebuilder/builder-cmweb-recipe.yaml` | New recipe version |

---

## 10. Gotchas

1. **`configurator/` is a submodule.** An empty directory means
   `git submodule update` was never run; `jobs_on_cloud/Makefile` will fail.
2. **Encrypted vars need `merge=binary`.** Never resolve a vault conflict by
   hand-merging ciphertext.
3. **`.vault`, `.key`, `.vault_password` are gitignored** — they exist on your
   machine, not in the repo.
4. **AMI builds are not reproducible** (`ParentImage: x.x.x`, `apt upgrade`,
   unpinned `apt` state).
5. **A failed image build leaves the instance running** — `stop instance if
   fail`. Look for orphaned `t3a.small` instances.
6. **`repo_sync_projects.sh` exits 0 when unconfigured.** A silent no-op.
7. **Stack name = template filename.** Renaming a template creates a second
   stack.
8. **Endpoints are duplicated across four files** with nothing enforcing
   agreement.
9. **Two Gerrit servers:** `review.ptc.sony.co.jp` (code being mirrored) vs
   `review-plus.ptc.sony.co.jp` (CMWEB's own source). Do not conflate.
10. **`ssm_parameter_name` contains the typo `cmeb`.**
11. **`defaults.yaml` pins `CMWEB_SLAVE_22`** but `agent/` only defines 18.04
    and 20.04 variable files.
