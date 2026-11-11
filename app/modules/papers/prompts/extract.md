你是计算力学 / 固体力学方向的论文信息抽取专家。下面是一篇论文的 Markdown 全文（公式/表格可能不完整）。

任务：**只抽取论文中明确写出的事实**，输出**一个 JSON 对象**（不要输出解释、不要编造）。找不到的字段写 `"unknown"`；数值必须带单位，并尽量注明来源（章节号 / 图 / 表号）。把 JSON 放进一个 ```json 代码块里输出。

JSON 结构（保持这些键）：

{
  "meta": {"title": "", "authors": "", "year": "", "journal": ""},
  "problem": "研究问题与目标",
  "governing_equations": [{"latex": "LaTeX 公式", "meaning": "物理含义", "source": "§2.1"}],
  "weak_form": [{"latex": "弱形式", "source": "§2.3"}],
  "constitutive_models": [{"name": "", "equations": "本构关系（LaTeX 或文字）", "assumptions": "", "source": ""}],
  "parameters": [{"name": "", "value": "", "unit": "", "source": "Table 1"}],
  "boundary_conditions": [{"type": "", "description": "", "source": ""}],
  "initial_conditions": [{"type": "", "description": "", "source": ""}],
  "geometry": {"dimension": "", "size": "", "symmetry": "", "source": ""},
  "mesh": {"element": "", "size": "", "refinement": "", "source": ""},
  "solver": {"study_type": "", "time_step": "", "nonlinear": "", "solver": "", "convergence": "", "source": ""},
  "validation": [{"figure": "Fig. 5", "description": "", "source": ""}],
  "missing_for_comsol": ["论文未给出、但 COMSOL 建模需要的信息"]
}

论文 Markdown：

<<<PAPER>>>
{paper}
<<<END>>>
