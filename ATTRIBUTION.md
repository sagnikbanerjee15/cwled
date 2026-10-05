# Third-Party Attribution

CWLed is distributed under the GNU General Public License v3.0 or later
(see `cwled/COPYING`
and `cwled/COPYRIGHT_NOTICE`). This file records third-party code, data, and
assets that CWLed bundles or depends on, together with their own licenses.
Those licenses continue to apply to those components.

## Bundled data

### EDAM ontology — `resources/ontologies/EDAM.tsv`, `resources/ontologies/EDAM_1.25.tsv`

EDAM is an ontology of bioinformatics data types, formats, operations and
topics, used here to populate format and topic pickers. The files are tabular
exports (NCBO BioPortal column layout) of EDAM version 1.25.

- Project: <https://edamontology.org/>
- Source repository: <https://github.com/edamontology/edamontology>
- License: Creative Commons Attribution-ShareAlike 4.0 International
  (CC BY-SA 4.0) — <https://creativecommons.org/licenses/by-sa/4.0/>
- Citation: Ison, J. *et al.* (2013) "EDAM: an ontology of bioinformatics
  operations, types of data and identifiers, topics and formats."
  *Bioinformatics* 29(10): 1325–1332. doi:10.1093/bioinformatics/btt113

CC BY-SA 4.0 requires attribution and that modified versions of these data
files be shared under the same license. The files are redistributed here
unmodified apart from format conversion.

## Bundled assets

### Common Workflow Language logo 

The CWL logo identifies the Common Workflow Language project. CWLed is an
independent tool and is not endorsed by or affiliated with the CWL project.

- Project: <https://www.commonwl.org/>
- Source repository: <https://github.com/common-workflow-language/common-workflow-language>
- The CWL specification and associated project materials are published under
  the Apache License 2.0.

### Icons

interface icons :
  <a href="https://www.flaticon.com/free-icons/add" title="add icons">Add icons created by Pixel perfect - Flaticon</a>,

  <a href="https://www.flaticon.com/free-icons/code" title="code icons">Code icons created by Royyan Wijaya - Flaticon</a>,
  
  <a href="https://www.flaticon.com/free-icons/delete" title="delete icons">Delete icons created by Those Icons - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/edit" title="edit icons">Edit icons created by Magnific - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/info-button" title="info button icons">Info button icons created by Mariana A - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/save" title="save icons">Save icons created by Yogi Aprelliyanto - Flaticon</a>,
  
  <a href="https://www.flaticon.com/free-icons/installation" title="installation icons">Installation icons created by Magnific - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/flow-chart" title="flow chart icons">Flow chart icons created by Anggara - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/sparkle" title="sparkle icons">Sparkle icons created by kornkun - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/box" title="box icons">Box icons created by Magnific - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/reload" title="reload icons">Reload icons created by Pixel perfect - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/sorting" title="sorting icons">Sorting icons created by icon wind - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/eyes" title="eyes icons">Eyes icons created by Kiranshastry - Flaticon</a>,
  
  <a href="https://www.flaticon.com/free-icons/arrow" title="arrow icons">Arrow icons created by ekays.dsgn - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/continuous" title="continuous icons">Continuous icons created by meaicon - Flaticon</a>, 
  
  <a href="https://www.flaticon.com/free-icons/commit-git" title="commit-git icons">Commit-git icons created by Magnific - Flaticon</a>,
  
  <a href="https://www.flaticon.com/free-icons/commit-git" title="commit git icons">Commit git icons created by icon_small - Flaticon</a>

### Rabix Composer look and feel — `cwled/theme.py`

The user interface theme (colour palette, layout, typography and icon choice)
reproduces the design of Rabix Composer, the CWL editor by Seven Bridges.
No Composer source code is included; colour values were taken from its
style sheets, the Ace "idle_fingers" editor theme and the cwl-svg
"rabix-dark" graph theme.

- Project: <https://github.com/rabix/composer>, <https://github.com/rabix/cwl-svg>
- License: Apache License 2.0

### Fonts — `resources/fonts/`

Both fonts are the versions shipped with Rabix Composer.

- **Montserrat** (`Montserrat-Regular.ttf`, `Montserrat-Light.ttf`), used for
  titles. Copyright (c) 2014 Julieta Ulanovsky.
  <https://github.com/JulietaUla/Montserrat> — SIL Open Font License 1.1
  (`resources/fonts/OFL-Montserrat.txt`).
- **Font Awesome 4.7.0** (`fontawesome-webfont.ttf`), used for icons.
  Copyright (c) 2016 Dave Gandy. <https://fontawesome.com/v4/> — SIL Open
  Font License 1.1 (`resources/fonts/OFL-FontAwesome.txt`).


## Runtime dependencies

Installed by the package manager rather than vendored; declared in
`pyproject.toml`. Licenses below are as reported by the distributed package
metadata.

### Copyleft — affects redistribution of built binaries

| Component | License |
| --- | --- |
| PyQt6 | GPL v3, or a commercial license from Riverbank Computing |
| PyQt6-QScintilla | GPL v3 |
| PyQt6-Qt6 (bundled Qt libraries) | LGPL v3 |

The PyInstaller bundles produced by `make` / `cwled.spec` embed PyQt6 and Qt.
Distributing those binaries means distributing GPL/LGPL components, which is
consistent with CWLed's own GPL license but requires that the corresponding
source offer and license texts accompany the release artifacts.

### Permissive

| Component | License |
| --- | --- |
| OdenGraphQt (node graph widget; fork of NodeGraphQt) | MIT |
| — CWLed resolves this to a PyQt6 fork via `[tool.uv.sources]`, not PyPI | MIT (inherited from OdenGraphQt) |
| QtPy | MIT |
| cwltool | Apache 2.0 |
| cwl-utils | Apache 2.0 |
| schema-salad | Apache 2.0 |
| cwlformat | see project  |
| ruamel.yaml, ruamel.yaml.clib, ruamel.yaml.string | MIT |
| langchain, langchain-core, langchain-openai, langchain-google-genai, langchain-anthropic | MIT |
| colorlog | MIT |
| markdown2 | MIT |
| platformdirs | MIT |
| Jinja2 | BSD-3-Clause |
| python-dotenv | BSD-3-Clause |
| GitPython | BSD-3-Clause |
| guidata | BSD-3-Clause |
| requests | Apache 2.0 |
| watchdog | Apache 2.0 |
| nested-lookup | Public Domain |
| pydantic | MIT |
| h5py | BSD-3-Clause |

For the authoritative, resolved set of dependencies and versions actually
installed, see `uv.lock`.
