# Working with TwinCheck

This private GitHub repository is already created and populated.

## Clone

    git clone https://github.com/ArnabIITP/TwinCheck.git
    cd TwinCheck
    python -m pip install -e .
    python -m unittest discover -s tests -v

## Development workflow

Create a feature branch for meaningful changes:

    git switch -c feat/short-description

Run the tests and CLI help before committing:

    python -m unittest discover -s tests -v
    python -m twincheck --help
    python -m twincheck compare --help

Keep the repository private while the early implementation is being reviewed. Before a public launch, re-check the license, security policy, CI results, package metadata, examples, and repository settings. Never advertise TwinCheck as a sandbox or proof of program equivalence.
