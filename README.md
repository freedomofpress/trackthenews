# Track The News

`trackthenews` is the script that powers [@FOIAfeed](https://twitter.com/foiafeed), a Twitter bot that monitors news outlets for reporting that incorporates public records laws like the Freedom of Information Act (FOIA), and tweets links to and excerpts from matching articles. The underlying software can track any collection of RSS feeds for any keywords.

If you want to run your own instance of `trackthenews`, you can download and install the package, and run its built-in configuration process. It can be installed with `pip`:

Python 3.9 is what we currently test against, though it may work with other versions.


```bash
pip3 install trackthenews
```

or by cloning the GitHub repository and running `setup.py`:

```bash
python3 setup.py install
```

Once it is installed, you can create a configuration by running the following command in the appropriate directory:

```bash
trackthenews --config
```

By default, the script will place all configuration files in a new `ttnconfig` folder in your current working directory, but you can also designate a directory for it to use.

```bash
python3 trackthenews --config ~/foo/bar/path
```

That configuration process will create the necessary files and walk you through setting up a Twitter bot for matching stories. After it is configured, you'll need to use a text editor to add the `matchwords` and RSS feeds to their respective files.

Sample RSS feed and matchword files can be found in the project's GitHub repo. The RSS feed file is a JSON array of objects corresponding to each feed. Each object requires a `url` field, and should also have an `outlet` field.

The next two fields are optional: if you know the feed uses redirect URLs, you may set `redirectLinks` to `true` and the script will attempt to follow those redirects to store and tweet canonical URLs; if the feed uses URLs that depend on query- or hash-strings to display correctly—basically, if the content relies on text in the URL bar after a `?` or `#`—you can set `delicateURLs` to `true` and the script will leave the URLs exactly as is.

Once you've got everything set up, you can run the program without the `--config` flag to check for matching articles.

```bash
trackthenews
```

If you designated a custom installation directory, or if you're running it from another directory (or a `cron` job, for example) you will need to designate the directory in which the configuration files are installed.

```bash
trackthenews ~/foo/bar/path
```

Settings, such as the background color for new posts, the font, and the user-agent, are all located in `config.yaml`, in the designated configuration directory. 

## How it works

Most of the script is dedicated to the `Article` class.
* `Article`s are created based on inputs. Currently those inputs are RSS feeds, which are stored in `rssfeeds.json`, but in future versions other inputs will include direct URLs, news APIs, Twitter feeds, or scraped pages.
* A series of `Article` methods then scrape and isolate the contents of each article (currently that cleanup is done with a [Python port of Readability](https://github.com/buriy/python-readability), but future versions may incorporate some per-site parsing), check whether it's suitable for posting, and then prepare images for tweeting.
* Finally, the `Article` tweets itself.

All articles are recorded in a sqlite database.

### Advanced feature: blocklist

In some cases, you may wish to suppress articles from being posted, even though they would otherwise match. You can do so by writing a new function, `check`, and placing it in a file named `blocklist.py` in the configuration directory. `check` takes an Article (and so has access to its `outlet`, `title`, and `url`) and should return `true` for any article that should be skipped.

## Development

### Quick Start

```bash
poetry env use 3.9  # Necessary if you have a different default python version
poetry install
poetry run trackthenews sample_project
# Follow the setup script instructions
cat sample_project/matchlist-sample.txt > sample_project/matchlist.txt
cat sample_project/rssfeeds-sample.json > sample_project/rssfeeds.json
poetry run trackthenews sample_project
```

### Detailed Instructions

To develop `trackthenews`, clone the repository and install the package using [poetry][] and run the CLI tool:

```bash
# Ensure you're using Python 3.9
poetry env use 3.9
# This will create a virtual environment and install trackthenews and its dependencies
poetry install --with=dev
# This will run the setup script
poetry run trackthenews sample_project
```

On first run this will take you through the interactive setup process. Follow the instructions. You will need a Twitter account with application keys and/or a Mastodon account.

When the setup process is complete, the configuration for your bot will live in the `sample_project` directory. Fill out the `matchlist.txt`, `matchlist_case_sensitive.txt`, and `rssfeeds.json` files or copy configuration from the provided samples:

```bash
cat sample_project/matchlist-sample.txt > sample_project/matchlist.txt
cat sample_project/rssfeeds-sample.json > sample_project/rssfeeds.json
```

`matchlist_case_sensitive.txt` is optional and we don't provide a sample.

Now run the bot:

```bash
poetry run trackthenews sample_project
```

[poetry]: https://python-poetry.org/

### Linters

We check that all code conforms to [black][], [flake8][], and [isort][]. To run these checks locally:

```bash
poetry run black --check .  # To automatically fix issues, exclude --check flag
poetry run flake8
poetry run isort --check-only --diff .  # To automatically fix issues, exclude --check-only and --diff flag
```

We also provide the following makefile shortcuts to run these commands:

```bash
make black
make flake8
make isort
make black-fix  # Automatically fix issues
make isort-fix  # Automatically fix issues
make all        # Run all three checks (check only, no fixes)
```

[black]: https://black.readthedocs.io/en/stable/
[flake8]: https://flake8.pycqa.org/en/latest/
[isort]: https://pycqa.github.io/isort/

## License

MIT.
