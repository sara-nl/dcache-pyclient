# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html


# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'dcache-pyclient'
copyright = '2026, Onno Zweers, Haili Hu'
author = 'Onno Zweers, Haili Hu'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    "sphinx.ext.napoleon",
    'sphinx.ext.intersphinx',
    'myst_parser',
    'sphinx_rtd_theme',
]

source_suffix = ['.rst', '.md']

# Show type hints in the parameter descriptions instead of in the
# signature, and document members in source order instead of alphabetically.
# Only for documented parameters, so a dataclass doesn't get a list of its
# fields as undocumented parameters on top of the documented fields.
autodoc_typehints = 'description'
autodoc_typehints_description_target = 'documented_params'
autodoc_member_order = 'bysource'

# Link types from the standard library (datetime, Path, ...) to the Python docs
intersphinx_mapping = {'python': ('https://docs.python.org/3', None)}
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
language = 'en'

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = []
