# Build/deployment repository

- This repository is public. It holds exported browser runtime files and deployment tools only.
- Never import the private Unity project, editable artwork, credentials, Library/, Assets/, Packages/ or ProjectSettings/.
- Stage a completed export with `python3 Tools/webgl_deploy.py stage /path/to/export`.
- site/ is generated and checksummed. Replace it using the stage command; do not edit payloads manually.
- _site/ is generated, ignored by Git and is the only directory deployed to Pages.
- Run `python3 -m unittest discover -s Tools -p 'test_webgl_deploy.py'` after tooling changes.
- Distinguish tooling tests, successful deployment and an actual hosted browser playtest.
- The game export is supplied from a locally tested Unity Web build; this repository does not build game source.
