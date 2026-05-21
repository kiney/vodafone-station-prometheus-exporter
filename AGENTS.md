This repo is the starting point for a small daemon to scrape metrics, especially DOCSIS status
from a vodafone station SOHO router.

Architecture:
python + flask
scrape the webinterface of the station to get DOCSIS status and perhaps other metrics
export prometheus metrics on configurable port
additionally allow writing a local log in sqlite and make snapshots in a "snapshots/" directoy.
There are some manually created examplex on how they should be name and what content they contain.
(it was just copy-pasted from the webinterface)

Rules:
NEVER read @config.yml directly as it contains sensitive credentials.
But you can run code that uses the conf file.
The format is documented in @README.md
