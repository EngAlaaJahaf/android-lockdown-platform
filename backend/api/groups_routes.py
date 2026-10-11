"""Device Groups API surface — mirrors the ManageEngine reference screens.

RBAC mapping (the permission set the console already uses):
  VIEW            read groups / members / profiles / status
  CREATE, EDIT    create and modify a group or its membership / associations
  APPLY           trigger a deployment to group members (BULK_APPLY is the
                  reference's "apply to all devices in group", which needs the
                  approval gate, so it is only used when the caller asks for it)
  RETIRE          deleting a group destroys the association to every profile, so
                  it is gated on the most destructive existing operation

Every deployment outcome reported here is derived from `assignments` rows; a
staged apply is never presented as a success.
"""

# Groups ---------------------------------------------------------------------
GROUPS = "Device Groups"

# --- read --------------------------------------------------------------------
# GET /api/v1/groups                      list groups with member/profile counts
# GET /api/v1/groups/{id}                 group detail (+ members, profiles)
# GET /api/v1/groups/{id}/members         Devices tab
# GET /api/v1/groups/{id}/profiles        Profiles tab with execution status
# GET /api/v1/groups/{id}/status          Execution status summary
# GET /api/v1/groups/{id}/actions         group_action_history

# --- write -------------------------------------------------------------------
# POST   /api/v1/groups                   create
# PUT    /api/v1/groups/{id}              rename / re-describe
# DELETE /api/v1/groups/{id}              delete (cascades members + assignments)
# POST   /api/v1/groups/{id}/members      add devices -> auto-deploys profiles
# DELETE /api/v1/groups/{id}/members/{device_id}
# POST   /api/v1/groups/{id}/move         move a device between groups
# POST   /api/v1/groups/{id}/profiles     associate profiles -> auto-deploys
# DELETE /api/v1/groups/{id}/profiles/{policy_id}
# POST   /api/v1/groups/{id}/deploy       apply now