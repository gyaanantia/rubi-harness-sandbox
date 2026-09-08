---
name: crm_sync_rules
description: Map document facts into the CRM
use_when: Syncing a deal
version: 1
---
Read field definitions before writing. deal_source_individual holds one
contact id. When a document names multiple introducing bankers, ask for one
using entity options. A skip or rejected choice drops that field. Do not
ask again within that run. Other work can continue.
For a failed sync, ask retry/exclude/map. Exclude drops the field; map asks
for a different valid contact before another write. A retry cap is final.
