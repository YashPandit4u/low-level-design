# Low Level Design

Articles and implementations by Yash Pandit.

## Splitwise

- [Read the article](https://yashpandit4u.github.io/low-level-design/splitwise/)
- [Article Markdown](splitwise/TUTORIAL-DETAILED.md)


## Local preview

Run `python3 -m http.server 8765` in this folder, then open http://localhost:8765/splitwise/.

## Update the pages

```sh
python3 -m pip install -r splitwise/requirements.txt
python3 splitwise/build.py
```

Commit the regenerated HTML. GitHub Pages publishes `main` from the repository root. `.nojekyll` serves the static files directly.

## Checks

```sh
cd splitwise
python3 -m unittest test_splitwise.py
javac Splitwise.java SplitwiseTest.java
java SplitwiseTest
```

The reading interface was inspired by Hello Interview. This is an independent study article. Open Sans is distributed under the SIL Open Font License; see `splitwise/assets/OFL.txt`.

## ATM

[Read the ATM article](https://yashpandit4u.github.io/low-level-design/atm/) · [Source and tests](atm/)
