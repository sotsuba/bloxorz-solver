# Contributing

## Bad commit vs Good commit?
- Bad commit: is one that is too large, mixes unrelated changes, or is difficult to review.
- Good commit: small, focused, and easy to understand. Each commit should represent one logical change.

## Common workflows

1. Pull the latest code from `main`.
2. Create a new branch following the naming convention `<firstname>/<feature-short-name-in-kebab-case>`.
3. Code code code.
4. Test test test.
5. Once everything looks good, write a proper commit message. Ideally, your first commit should match the [pull request title](https://discord.com/channels/1411031635725385918/1481884089123344545/1481884303909458055), since GitHub will use it as the default PR title, saving you the trouble of editing it. Subsequent commits can be named however you like, since they'll be squash-merged anyway (except when [syncing upstream](https://discord.com/channels/1411031635725385918/1481884089123344545/1510928422417858580) or preparing a release).
6. Need to make changes? Just commit again. Once everything's ready, push your branch and open a pull request.&#x20;
7. Once everything looks good, ping the code owner and let them stare at your code. That's it.

## Must read resources
**About commit conventions:**
- [Commit message conventions (just for fun, we squash and merge anyway)](https://www.conventionalcommits.org/en/v1.0.0/)
- [Why Write Small CLs?](https://google.github.io/eng-practices/review/developer/small-cls.html)
- [Committing in two phases](https://github.com/git-guides/git-commit#committing-in-two-phases)

**About pull request conventions:**
- [Pull request conventions](https://cadenceworkflow.io/community/how-to-contribute/pull-request-conventions)