# lambdavault compatibility report · [tasks](TASKS.md)

Not run yet: the comparison needs a deployed stack.

    LAMBDAVAULT_TOKEN=<token> python3 -m pytest tests -q --docker run --aws my.json

regenerates this file (Vault 1.20.3 in Docker vs the deployed lambdavault).
