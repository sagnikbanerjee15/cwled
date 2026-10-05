sc:external_links: '[{"URL": "https://www.commonwl.org/user_guide/topics/inputs.html#inclusive-and-exclusive-inputs", "type": "Documentation"}]'
class: CommandLineTool
id: records
label: Test records
doc: |-
  <p>This is a test script for records in CWL</p>
  <p>In the dependent parameters example, you can’t provide itemA without also providing itemB.
  but you can provide only itemB</p>
  <p>In the second example, itemC and itemD are exclusive, so only the first matching item (itemC) is added to the command line and remaining item (itemD) is ignored even if provided</p>
  <p>For defaults
  For dependent variables we just set them like
  default: # Use a mapping, not a list
  itemA: "defaultA"
  itemB: "defaultB"
  For mutually exclusive we need to define which is the default and its value</p>
inputs:
- id: input_string
  type: string
  default: input_string_default
  inputBinding:
    position: 10
    prefix: -S
- id: input_integer
  type:
    - 'null'
    - float
  default: 10
  inputBinding:
    position: 15
    prefix: -i
- id: dependent_parameters
  default:
    itemA: default_A
    itemB: default_B
  type:
    name: dependent_parameters
    fields:
    - name: itemA
      type: string
      inputBinding:
        prefix: -A
    - name: itemB
      type: string
      inputBinding:
        prefix: -B
    type: "record"
- id: exclusive_parameters
  default:
    class: itemC
    itemC: default_C
  type:
  - name: itemC
    fields:
    - name: itemC
      type: string
      inputBinding:
        prefix: -C
    type: record
  - name: itemD
    fields:
    - name: itemD
      type: string
      inputBinding:
        prefix: -D
    type: record
outputs:
- id: example_out
  type: "stdout"
cwlVersion: v1.2
baseCommand:
- echo
stdout: "output.txt"
$namespaces:
  "sc": "https://schema.org/"
