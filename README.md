See https://github.com/CodeOptimist/rimworld-mod-description-tool for example inheritance.

```yaml
---
fruit1: &fruit1
  - name: 'Strawberry'
  - name: 'Apple'
  - name: 'Banana'

fruit1_names: &fruit1_names !each [ *fruit1, 'name' ]
fruit1_names_joined: !join [ ", ", *fruit1_names ]
fruit1_names_sliced: !each [ *fruit1, 'name', '{l|_,3}' ]

fruit2: &fruit2
  - property: &strawberry { common: 'Strawberry', scientific: 'Fragaria × ananassa' }
  - property: { common: 'Apple', scientific: 'Malus domestica' }
  - property: { common: 'Banana', scientific: 'Musa acuminata' }

fruit2_property: !each [ *fruit2, 'property' ]
fruit2_scientific_joined: !join [ ", ", !each [ *fruit2, 'property.scientific' ] ]

fruit3: &fruit3 !insert
  - [ *fruit1 ]
  - name: 'Pineapple'
fruit3_names: !each [ *fruit3, 'name' ]

has_dog: ~
dog: 'a dog named "[BRACKY]"'
has_cat: Yup
cat: 'a cat named "{{CURLY}}"'

matrix: &matrix !concat
  - [ 1, 2, 3 ]
  - [ 4, 5, 6 ]
  - [ 7, 8, 9 ]
float_matrix: !each [ *matrix, ~, '{l:.3f}' ]

fruit4: !merge
  <: *strawberry
  color: 'red'

# [text to format, expected literal result]
tests:
  - [ '{fruit1_names}', "['Strawberry', 'Apple', 'Banana']" ]
  - [ '{fruit1_names_joined}', 'Strawberry, Apple, Banana' ]
  - [ '{fruit1_names_sliced}', "['Str', 'App', 'Ban']" ]
  - [ '{fruit2_scientific_joined}', 'Fragaria × ananassa, Malus domestica, Musa acuminata' ]
  - [ '{fruit3_names}', "['Strawberry', 'Apple', 'Banana', 'Pineapple']" ]
  - [ '{dog}', 'a dog named "[BRACKY]"' ]
  - [ '{has_dog?={{dog}} is {dog}}', '' ]
  - [ '{cat}', 'a cat named "{CURLY}"' ]
  - [ '{has_cat?={{cat}} is {cat}}', '{cat} is a cat named "{CURLY}"' ]
  - [ '{has_cat?+ sure do.}', 'Yup sure do.' ]
  - [ '{optional?}', '' ]
  - [ '{matrix}', '[1, 2, 3, 4, 5, 6, 7, 8, 9]' ]
  - [ '{fruit4!e}', "{'common': 'Strawberry', 'scientific': 'Fragaria × ananassa', 'color': 'red'}" ]
  - [ '{float_matrix}', "['1.000', '2.000', '3.000', '4.000', '5.000', '6.000', '7.000', '8.000', '9.000']" ]
  - [ '{fruit1.name^Apple!e}', "{'name': 'Apple'}" ]
  - [ '{fruit2_property.common^Banana!e}', "{'common': 'Banana', 'scientific': 'Musa acuminata'}" ]
```