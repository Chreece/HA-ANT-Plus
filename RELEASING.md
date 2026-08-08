# Releasing HA ANT+

1. Update `custom_components/antplus/manifest.json` `version`.
2. Run the test suite locally if possible.
3. Push to GitHub and wait for HACS, Hassfest and Tests workflows to pass.
4. Create a GitHub release whose tag matches the manifest version, for example `0.4.0` or `v0.4.0`.
5. Test installation/update through HACS as a custom repository.
6. When ready for HACS default inclusion, follow the current HACS publishing requirements and submit the repository to `hacs/default`.

For GitHub, set the repository description and topics, enable Issues, and optionally upload `assets/github-social-preview.png` under repository social preview settings.
