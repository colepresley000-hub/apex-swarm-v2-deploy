"""
Patch: Add Live Swarm View page to main.py
Serves swarm_view.html at /swarm

Run:
  python3 patch_swarm_view.py
"""

import sys

try:
    with open("swarm_view.html", "r") as f:
        html = f.read()
    print(f"✅ Read swarm_view.html ({len(html)} chars)")
except FileNotFoundError:
    print("❌ swarm_view.html not found")
    sys.exit(1)

with open("main.py", "r") as f:
    content = f.read()

# Add the route before the dashboard route
route_code = f'''
SWARM_VIEW_HTML = r"""{html}"""


@app.get("/swarm", response_class=HTMLResponse)
async def swarm_view():
    return HTMLResponse(SWARM_VIEW_HTML)


'''

# Insert before LANDING_HTML or DASHBOARD_HTML
if "LANDING_HTML = r" in content:
    content = content.replace("LANDING_HTML = r", route_code + "LANDING_HTML = r", 1)
elif "DASHBOARD_HTML = r" in content:
    content = content.replace("DASHBOARD_HTML = r", route_code + "DASHBOARD_HTML = r", 1)
else:
    print("❌ Could not find insertion point")
    sys.exit(1)

with open("main.py", "w") as f:
    f.write(content)

# Verify
with open("main.py", "r") as f:
    v = f.read()

if "swarm_view" in v and "swarmCanvas" in v:
    print("✅ Swarm View patched successfully")
    print("   Route: /swarm")
else:
    print("❌ Patch may have failed")

print("\nNext:")
print("  git add -A")
print("  git commit -m 'v5: live swarm visualizer'")
print("  railway up")
