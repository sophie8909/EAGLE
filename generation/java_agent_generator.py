"""Structured behavior generation, validation, rendering, and persistence."""
from __future__ import annotations
import json, shutil
from dataclasses import dataclass, field
from pathlib import Path
from eagle.candidate import Candidate, MODULE_NAMES
from evaluation.code_quality import FunctionScoreResult, evaluate_function_output
from .agent_template import JavaTemplatePaths, load_java_templates, render_behavior_template
from .backend import GenerationBackend
from .java_module_validator import validate_function_module

@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    error: str = ""

@dataclass(frozen=True)
class GeneratedJavaAgent:
    class_name: str; package_name: str; source: str; source_path: Path; behavior_source: str; behavior_source_path: Path
    raw_llm_output: str = ""; extracted_code: str = ""
    module_raw_outputs: dict[str,str] = field(default_factory=dict); module_bodies: dict[str,str] = field(default_factory=dict)
    validation_result: ValidationResult = field(default_factory=lambda: ValidationResult(True))
    @property
    def qualified_class_name(self)->str: return f"{self.package_name}.{self.class_name}"
    @property
    def source_paths(self)->tuple[Path,Path]: return self.source_path,self.behavior_source_path

@dataclass(frozen=True)
class JavaAgentGenerationResult:
    class_name: str="CandidateAgent"; package_name: str="ai.generated"; raw_llm_output: str=""; extracted_code: str=""
    module_raw_outputs: dict[str,str]=field(default_factory=dict); module_bodies: dict[str,str]=field(default_factory=dict); assembled_java: str=""
    validation_result: ValidationResult=field(default_factory=lambda:ValidationResult(False,"not_run")); function_score_result: FunctionScoreResult|None=None
    agent: GeneratedJavaAgent|None=None; failure_category: str|None=None; failure_reason: str|None=None

def generate_java_agent(candidate:Candidate,backend:GenerationBackend,workspace_dir:Path,*,template_paths:JavaTemplatePaths|None=None)->GeneratedJavaAgent:
    result=generate_java_agent_result(candidate,backend,workspace_dir,template_paths=template_paths)
    if result.agent is None: raise ValueError(result.failure_reason or "Java agent generation failed.")
    return result.agent

def generate_java_agent_result(candidate:Candidate,backend:GenerationBackend,workspace_dir:Path,*,template_paths:JavaTemplatePaths|None=None)->JavaAgentGenerationResult:
    paths=template_paths or JavaTemplatePaths()
    try:
        agent_template,behavior_template=load_java_templates(paths); raw=backend.generate(candidate,"CandidateAgent")
    except (RuntimeError,ValueError,OSError) as exc:
        reason=str(exc); return JavaAgentGenerationResult(raw_llm_output=locals().get("raw",""),validation_result=ValidationResult(False,reason),failure_category=classify_generation_error(reason),failure_reason=reason)
    functions=evaluate_function_output(raw,behavior_template)
    errors=function_output_errors(functions)
    if errors:
        reason="; ".join(errors)
        return JavaAgentGenerationResult(raw_llm_output=raw,module_raw_outputs={"all":raw},module_bodies=functions.bodies,validation_result=ValidationResult(False,reason),function_score_result=functions,failure_category="Java validation failure",failure_reason=reason)
    render_bodies=functions.bodies
    try: behaviors=render_behavior_template(behavior_template,render_bodies)
    except ValueError as exc:
        reason=str(exc); return JavaAgentGenerationResult(raw_llm_output=raw,module_bodies=functions.bodies,function_score_result=functions,validation_result=ValidationResult(False,reason),failure_category="Java validation failure",failure_reason=reason)
    package_dir=workspace_dir/candidate.id; package_dir.mkdir(parents=True,exist_ok=True)
    wrapper_path=package_dir/"CandidateAgent.java"; behavior_path=package_dir/"CandidateBehaviors.java"
    shutil.copyfile(paths.agent_template_path,wrapper_path); behavior_path.write_text(behaviors,encoding="utf-8")
    validation=ValidationResult(True,"")
    agent=GeneratedJavaAgent("CandidateAgent","ai.generated",agent_template,wrapper_path,behaviors,behavior_path,raw,json.dumps({"functions":functions.bodies},ensure_ascii=False),{"all":raw},functions.bodies,validation)
    return JavaAgentGenerationResult(raw_llm_output=raw,extracted_code=agent.extracted_code,module_raw_outputs={"all":raw},module_bodies=functions.bodies,assembled_java=behaviors,validation_result=validation,function_score_result=functions,agent=agent)

def function_output_errors(functions:FunctionScoreResult)->list[str]:
    return list(functions.parsing_errors)+[f"{name}: {error}" for name,item in functions.function_validation.items() for error in item.errors]

def parse_behavior_functions(raw:str)->dict[str,str]:
    _,template=load_java_templates(JavaTemplatePaths()); result=evaluate_function_output(raw,template)
    errors=list(result.parsing_errors)+[error for item in result.function_validation.values() for error in item.errors]
    if errors: raise ValueError("; ".join(errors))
    return {name:result.bodies[name] for name in MODULE_NAMES}

def assemble_java_agent(class_name:str,module_bodies:dict[str,str],*,template_paths:JavaTemplatePaths|None=None)->str:
    if class_name!="CandidateAgent": raise ValueError("Repository template declares only CandidateAgent.")
    for name in MODULE_NAMES: validate_function_module(module_bodies[name],name)
    _,template=load_java_templates(template_paths or JavaTemplatePaths()); return render_behavior_template(template,module_bodies)
def extract_code_from_output(raw_output:str)->str:return json.dumps({"functions":parse_behavior_functions(raw_output)},ensure_ascii=False)
def clean_generated_java_output(output:str)->str:return output.strip()
def normalize_java_agent_source(source:str)->str:return source
def validate_java_agent_source(source:str,class_name:str)->None:
    if f"public final class {class_name}" not in source: raise ValueError("Fixed wrapper class declaration is missing.")
def validate_assembled_java(source:str,class_name:str)->ValidationResult:return ValidationResult("EAGLE_BODY" not in source,"Unresolved EAGLE_BODY placeholder." if "EAGLE_BODY" in source else "")
def classify_generation_error(reason:str)->str:
    lowered=reason.lower()
    if "timeout" in lowered:return "Timeout"
    if "backend" in lowered or "http" in lowered:return "Backend request failure"
    return "Java validation failure"
