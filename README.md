# dtf README

Collect babymetal reaction videos from youtube and create playlists


## Local Development

Python: 3.9

> Requires [pipenv](https://pipenv.readthedocs.io/en/latest/) for dependency management
> Install with `pip install pipenv --user`



### Install the local development environment

1. Setup `pre-commit` hooks (_black_, _isort_):

    ```bash
    # assumes pre-commit is installed on system via: `pip install pre-commit`
    pre-commit install
    ```

2. The following command installs project and development dependencies:

    ```bash
    pipenv sync --dev
    ```

### Add new packages

From the project root directory run the following:
```
pipenv install {PACKAGE TO INSTALL}
```

 ## Run code checks

 To run linters:
 ```
 # runs flake8, pydocstyle
 make check
 ```

To run type checker:
```
make mypy
```

## Running tests

This project uses [pytest](https://docs.pytest.org/en/latest/contents.html) for running testcases.

Tests cases are written and placed in the `tests` directory.

To run the tests use the following command:
```
pytest -v
```

> In addition the following `make` command is available:

```
make test
```

## CI/CD Required Environment Variables

The following are required for this project to be integrated with auto-deploy using the `github flow` branching strategy.

> With `github flow` master is the *release* branch and features are added through Pull-Requests (PRs)
> On merge to master the code will be deployed to the production environment.

[[LIST REQUIRED ENVIRONMENT VARIABLES HERE]]
