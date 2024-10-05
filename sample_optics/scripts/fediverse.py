import os
from pathlib import Path
import json

file_path = Path(os.path.realpath(__file__))

# source of nodes list: https://nodes.fediverse.party/nodes.json
with open(
    file_path.parent.parent.joinpath("data").joinpath("fediverse_nodes.json")
) as f:
    sites = json.loads(f.read())


def rule(site):
    if site.count(".") > 1:
        return """
        Matches {{
            Site("|{0}|")
        }},""".format(
            site
        )
    else:
        return """
        Matches {{
            Domain("|{0}|")
        }},""".format(
            site
        )


optic = """DiscardNonMatching;

"""

optic += "// source of fediverse sites: https://nodes.fediverse.party/nodes.json\n"
optic += "Rule {"
optic += "".join([rule(site) for site in sites])
optic += "\n};"

print(optic)
