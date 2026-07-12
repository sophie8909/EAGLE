"""Structural validation for generated Java module methods."""
from eagle.module_contract import MODULE_METHOD_CONTRACTS

def tokens(source: str) -> list[str]:
    out=[]; i=0
    while i < len(source):
        c=source[i]
        if c.isspace(): i+=1; continue
        if source.startswith("//",i):
            n=source.find("\n",i); i=len(source) if n<0 else n+1; continue
        if source.startswith("/*",i):
            n=source.find("*/",i+2)
            if n<0: raise ValueError("Generated module method contains an unterminated comment.")
            i=n+2; continue
        if c in "\"'":
            q=c; j=i+1
            while j<len(source):
                if source[j]=="\\": j+=2
                elif source[j]==q: j+=1; break
                else: j+=1
            else: raise ValueError("Generated module method contains an unterminated literal.")
            out.append(source[i:j]); i=j; continue
        if c.isalpha() or c in "_$":
            j=i+1
            while j<len(source) and (source[j].isalnum() or source[j] in "_$"): j+=1
            out.append(source[i:j]); i=j; continue
        out.append(c); i+=1
    return out

def validate_function_module(source: str, module: str) -> None:
    contract=MODULE_METHOD_CONTRACTS[module]; ts=tokens(source)
    if not ts: raise ValueError("Generated module method must not be empty.")
    bad=next((x for x in ts if x in {"package","import","class","interface","enum","record"}),None)
    if bad: raise ValueError(f"Generated module method must not declare {bad}.")
    try: brace=ts.index("{"); paren=ts.index("(")
    except ValueError: raise ValueError("Generated module must be one complete Java method declaration.")
    header=ts[:brace]
    if header[0]!="private": raise ValueError("Generated module method must use private visibility.")
    if any(x in {"public","protected","static","final","abstract","synchronized","native","strictfp","default"} for x in header[1:]):
        raise ValueError("Generated module method contains unsupported modifiers.")
    if paren<3 or header[-1]!=")": raise ValueError("Generated module must be one complete Java method declaration.")
    name=header[paren-1]; returns="".join(header[1:paren-1])
    if name!=contract.method_name: raise ValueError(f"Generated module method name must be {contract.method_name}, got {name}.")
    if returns!=contract.return_type: raise ValueError(f"Generated {contract.method_name} return type must be {contract.return_type}, got {returns}.")
    groups=[]; cur=[]; depth=0
    for x in header[paren+1:-1]:
        depth += (x=="<")-(x==">")
        if x=="," and depth==0: groups.append(cur); cur=[]
        else: cur.append(x)
    if cur: groups.append(cur)
    actual=tuple("".join(g[:-1]) for g in groups if len(g)>=2)
    if len(actual)!=len(groups) or actual!=contract.parameter_types:
        raise ValueError(f"Generated {contract.method_name} parameter types must be ({', '.join(contract.parameter_types)}), got ({', '.join(actual)}).")
    depth=0; close=None
    for i in range(brace,len(ts)):
        depth += (ts[i]=="{")-(ts[i]=="}")
        if depth==0: close=i; break
    if close is None: raise ValueError("Generated module method has unbalanced braces.")
    if close!=len(ts)-1: raise ValueError("Generated module must contain exactly one top-level method declaration.")
    if close==brace+1: raise ValueError("Generated module method body must be non-empty.")
