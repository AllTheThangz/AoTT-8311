'use strict';
(function(){
    const form=document.getElementById('aott-access-form');
    if(!form) return;
    const message=document.getElementById('aott-access-message');
    const review=document.getElementById('aott-access-review');
    const diff=document.getElementById('aott-access-diff');
    const apply=document.getElementById('aott-access-apply');
    let reviewed=null;

    function endpoint(name){
        const raw=form.getAttribute(name)||'';
        try {
            const url=new URL(raw,window.location.href);
            return url.origin===window.location.origin ? url.pathname+url.search : null;
        } catch(e){ return null; }
    }
    function signature(){
        const rows=[];
        new FormData(form).forEach((value,key)=>rows.push([key,String(value)]));
        rows.sort((a,b)=>a[0].localeCompare(b[0]));
        return JSON.stringify(rows);
    }
    async function post(url,data){
        const body=new URLSearchParams();
        if(data instanceof FormData){
            data.forEach((v,k)=>body.append(k,String(v)));
        } else {
            Object.keys(data||{}).forEach(k=>body.append(k,String(data[k])));
            const token=form.querySelector('input[name="token"]');
            if(token && !body.has('token')) body.append('token',token.value);
        }
        const response=await fetch(url,{
            method:'POST',credentials:'same-origin',cache:'no-store',
            headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'},
            body:body.toString()
        });
        let record={};
        try { record=await response.json(); } catch(e) {}
        if(!response.ok || record.success!==true){
            const err=new Error(record.error || 'Access operation failed.');
            err.record=record; throw err;
        }
        return record;
    }
    function clearErrors(){
        form.querySelectorAll('[data-access-error]').forEach(el=>{
            el.style.display='none';el.textContent='';
        });
    }
    function showErrors(errors){
        if(!errors || typeof errors!=='object') return;
        Object.keys(errors).forEach(id=>{
            const el=form.querySelector('[data-access-error="'+CSS.escape(id)+'"]');
            if(el){el.textContent=String(errors[id]);el.style.display='block';}
        });
    }
    function renderDiff(rows){
        diff.textContent='';
        const table=document.createElement('table');
        table.className='table';
        const head=document.createElement('tr');
        ['Setting','Before','After'].forEach(label=>{
            const th=document.createElement('th');th.textContent=label;head.appendChild(th);
        });
        table.appendChild(head);
        (rows||[]).forEach(row=>{
            const tr=document.createElement('tr');
            [row.id,row.before,row.after].forEach(value=>{
                const td=document.createElement('td');td.textContent=String(value ?? '');tr.appendChild(td);
            });
            table.appendChild(tr);
        });
        diff.appendChild(table);
        review.hidden=false;
    }
    form.addEventListener('input',()=>{
        if(reviewed!==null && reviewed!==signature()){
            reviewed=null;apply.disabled=true;review.hidden=true;
            message.textContent='Settings changed after review. Review again before applying.';
        }
    });
    form.addEventListener('submit',async event=>{
        event.preventDefault();clearErrors();
        const url=endpoint('data-preview-url');
        if(!url){message.textContent='Access preview endpoint is invalid.';return;}
        apply.disabled=true;reviewed=null;
        message.textContent='Validating access configuration…';
        try{
            const record=await post(url,new FormData(form));
            renderDiff(record.diff||[]);
            reviewed=signature();
            apply.disabled=!record.changes_required;
            message.textContent=record.changes_required ?
                'Review complete. Apply starts a guarded transaction with automatic rollback.' :
                'No access settings changed.';
        }catch(error){
            showErrors(error.record && error.record.errors);
            message.textContent=error.message;
        }
    });
    apply.addEventListener('click',async()=>{
        if(!reviewed || reviewed!==signature()){
            apply.disabled=true;message.textContent='Review is stale. Review the settings again.';return;
        }
        const url=endpoint('data-apply-url');
        if(!url){message.textContent='Access apply endpoint is invalid.';return;}
        apply.disabled=true;
        message.textContent='Applying guarded access transaction…';
        try{
            const record=await post(url,new FormData(form));
            if(record.status==='ACCESS_TRANSACTION_NO_CHANGE'){
                message.textContent='No access settings changed.';return;
            }
            if(!record.job || !/^[0-9a-f]{32}$/.test(record.job.id||'')){
                throw new Error('Access transaction response was incomplete.');
            }
            const port=form.elements.web_https_port && form.elements.web_https_port.value;
            const target=new URL(window.location.href);
            target.protocol='https:';
            target.port=(port && port!=='443')?port:'';
            target.pathname=window.location.pathname;
            target.search='';target.hash='';
            message.textContent='';
            const text=document.createTextNode(
                'Access transaction started. Verify the intended access path, then reopen this page and confirm before automatic rollback. ');
            const link=document.createElement('a');
            link.href=target.toString();link.textContent='Open the intended HTTPS endpoint';
            message.appendChild(text);message.appendChild(link);
        }catch(error){
            apply.disabled=false;
            message.textContent=error.message+
                ' If the web listener moved before the response arrived, try the intended HTTPS endpoint and check the pending transaction.';
        }
    });

    const confirm=document.getElementById('aott-access-confirm-pending');
    if(confirm){
        confirm.addEventListener('click',async()=>{
            const section=document.getElementById('aott-access-pending');
            const status=document.getElementById('aott-access-confirm-status');
            const job=section && section.getAttribute('data-job-id');
            const url=endpoint('data-confirm-url');
            if(!url || !job || !/^[0-9a-f]{32}$/.test(job)){
                if(status) status.textContent='Pending access transaction data is invalid.';
                return;
            }
            confirm.disabled=true;
            if(status) status.textContent=' Confirming…';
            try{
                await post(url,{job_id:job});
                if(status) status.textContent=' Access settings confirmed.';
                confirm.textContent='Confirmed';
            }catch(error){
                confirm.disabled=false;
                if(status) status.textContent=' '+error.message;
            }
        });
    }
})();
