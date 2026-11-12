"use strict";
/* AoTT V3r4 read-only Configuration Verification Overview.
 * One operator-initiated pass across the seven existing authenticated
 * effective-state endpoints. Never displays device-provided values, PON
 * identity, management IPs, MACs, credentials or server error messages.
 * It is NOT a hardware-qualification or Internet-connectivity checker.
 */
(function () {
    const GROUPS=[
        {id:'management',label:'Management and access path',ids:[
            'lct_vlan','ipaddr','netmask','gateway','dns_server','pingd',
            'ping_ip','lct_mac','reverse_arp','https_redirect']},
        {id:'device',label:'Device and host-visible SFP',ids:[
            'hostname','lang','timezone','ntp_servers','sfp_vendor','sfp_oui',
            'sfp_partno','sfp_rev','sfp_serial','sfp_date','sfp_vendordata']},
        {id:'pon',label:'PON/OMCI configuration',ids:[
            'pon_mode','omcc_version','iop_mask','mib_file']},
        {id:'identity',label:'Sensitive stored identity overrides',ids:[
            'gpon_sn','vendor_id','reg_id_hex','loid','lpwd',
            'iphost_mac','iphost_hostname','iphost_domain','root_pwhash']},
        {id:'reporting',label:'OMCI reported metadata',ids:[
            'equipment_id','hw_ver','cp_hw_ver_sync','sw_verA','sw_verB',
            'fw_match_b64','fw_match_num','override_active','override_commit','pon_slot']},
        {id:'vlan',label:'ISP and local VLAN',ids:[
            'fix_vlans','internet_vlan','services_vlan']},
        {id:'hardware',label:'Advanced hardware options',ids:[
            'bootdelay','uart_select','console_en','dying_gasp_en',
            'rx_los','ethtool_speed','failsafe_delay','persist_root']}
    ];
    const STATUS=['match','mismatch','unverified'];
    let busy=false;

    function verifiedPath(group) {
        // A controller-generated same-origin, query-free path only. Do not
        // accept server-provided or user-edited URL destinations.
        const panel=document.getElementById('aott-'+group.id+'-effective');
        const raw=panel && panel.getAttribute('data-effective-url');
        const suffix='/admin/8311/effective_'+group.id;
        if (!raw || raw[0]!=='/' || raw.startsWith('//') || raw.includes('\\') ||
            raw.includes('%') || raw.includes('?') || raw.includes('#')) return null;
        let parsed;
        try { parsed=new URL(raw,location.href); } catch (_) { return null; }
        if (parsed.origin!==location.origin ||
            parsed.pathname!==raw || !parsed.pathname.endsWith(suffix) ||
            parsed.search || parsed.hash) return null;
        return raw;
    }
    function check(record,group) {
        const d=record && record.data;
        if (!record || record.success!==true || !d || d.schema!==1 ||
            d.no_device_write!==true || !d.fields ||
            typeof d.fields!=='object' || Array.isArray(d.fields) ||
            !d.summary || typeof d.summary!=='object') throw Error('invalid_contract');
        if (group.id==='management') {
            if (d.no_hidden_hardware_qualification!==true) throw Error('invalid_management_contract');
        } else if (d.source_only_not_hardware_qualified!==true) {
            throw Error('unqualified_contract_missing');
        }
        if ((group.id==='pon' || group.id==='vlan') &&
            d.contains_registration_secret!==false) throw Error('secret_contract_missing');
        if (group.id==='hardware' && d.contains_credential_material!==false)
            throw Error('secret_contract_missing');
        if (group.id==='identity' &&
            (d.no_identity_exported!==true ||
             d.no_credential_hash_exported!==true ||
             d.no_raw_environment_exported!==true ||
             d.no_olt_or_login_authentication_claim!==true))
            throw Error('redaction_contract_missing');
        if (group.id==='reporting' &&
            (d.no_registration_secret_read!==true ||
             d.no_subscriber_identity_exported!==true ||
             d.no_raw_environment_value_exported!==true ||
             d.no_olt_effect_proof!==true))
            throw Error('redaction_contract_missing');
        if (Object.keys(d.fields).length!==group.ids.length)
            throw Error('unexpected_field_set');

        const rows=[], totals={observed:0,drift:0,unverified:0,invalid:0};
        for (const id of group.ids) {
            const field=Object.prototype.hasOwnProperty.call(d.fields,id) && d.fields[id];
            if (!field || field.id!==id || field.hardware_qualified!==false ||
                field.runtime_effect_proven!==true && field.runtime_effect_proven!==false)
                throw Error('invalid_field_contract');
            if (group.id==='identity') {
                const states=['valid_saved_override','invalid_saved_override','unset','unavailable'];
                if (!states.includes(field.source_status) ||
                    field.content_redacted!==true || field.raw_value_exported!==false ||
                    field.value_hash_exported!==false ||
                    field.authentication_success_proven!==false)
                    throw Error('invalid_identity_contract');
            }
            if (group.id==='reporting' &&
                (field.content_redacted!==true || field.raw_value_exported!==false ||
                 field.olt_received_reported_value_proven!==false))
                throw Error('invalid_reporting_contract');
            if (group.id==='identity' || group.id==='reporting') {
                if (field.runtime_effect_proven!==false)
                    throw Error('invalid_source_only_claim');
            }
            let state='Unverified',source='Not independently observed',drift=false,invalid=false;
            if (group.id==='identity') {
                state={
                    valid_saved_override:'Stored format valid; effect unverified',
                    invalid_saved_override:'Invalid stored format; effect unverified',
                    unset:'Stored override unset; defaults unverified',
                    unavailable:'Source unavailable'
                }[field.source_status];
                invalid=field.source_status==='invalid_saved_override';
                source='Redacted source only';
            } else if (group.id==='reporting') {
                const format=field.source_format;
                if (!['valid_source_format','invalid_source_format',
                       'absent','unavailable'].includes(format))
                    throw Error('invalid_reporting_format');
                state=format==='invalid_source_format' ?
                    'Invalid stored format; OLT effect unverified' :
                    format==='valid_source_format' ?
                    'Stored format valid; OLT effect unverified' :
                    'Stored source unavailable or unset';
                invalid=format==='invalid_source_format';
                source='Redacted source only';
            } else {
                const compare=field.saved_to_configured;
                const observed=field.saved_to_observed;
                if (compare!==undefined && !STATUS.includes(compare))
                    throw Error('invalid_saved_comparison');
                if (observed!==undefined && !STATUS.includes(observed))
                    throw Error('invalid_runtime_comparison');
                if (group.id==='vlan') {
                    if (field.saved_to_last_recorded!==undefined &&
                        !STATUS.includes(field.saved_to_last_recorded))
                        throw Error('invalid_historical_comparison');
                }
                drift=(compare==='mismatch' ||
                       (field.runtime_effect_proven===true && observed==='mismatch'));
                if (field.runtime_effect_proven===true) {
                    state=observed==='match'?'Observed; matches saved':
                          observed==='mismatch'?'Observed; differs from saved':
                          'Observed; comparison unavailable';
                    source='Independent runtime observation';
                    totals.observed++;
                } else if (drift) {
                    state='Saved/configured difference; runtime unverified';
                    source='Configuration-only evidence';
                } else if (group.id==='vlan' &&
                           field.saved_to_last_recorded==='mismatch') {
                    state='Historical reconciliation differs; current effect unverified';
                    source='Historical record, not current runtime';
                } else if (field.configured_value!==undefined &&
                           field.configured_value!==null) {
                    state='Configured; runtime effect unverified';
                    source='Configured state only';
                } else {
                    state='Runtime effect unverified';
                }
            }
            if (drift) totals.drift++;
            if (invalid) totals.invalid++;
            if (field.runtime_effect_proven!==true) totals.unverified++;
            rows.push({id,state,source});
        }
        return {group,rows,totals};
    }
    function cell(tr,value,tag) {
        const el=document.createElement(tag||'td');
        el.textContent=String(value);tr.appendChild(el);return el;
    }
    function render(result,errors) {
        const target=document.getElementById('aott-verification-results');
        const status=document.getElementById('aott-verification-status');
        if (!target || !status) return;
        target.replaceChildren();
        const complete=result.length;
        const total=result.reduce((x,r)=>x+r.group.ids.length,0);
        const observed=result.reduce((x,r)=>x+r.totals.observed,0);
        const drift=result.reduce((x,r)=>x+r.totals.drift,0);
        const invalid=result.reduce((x,r)=>x+r.totals.invalid,0);
        const summary=document.createElement('p');
        summary.textContent=complete+'/7 checks completed; '+total+
            '/55 source fields read; '+observed+
            ' runtime observations; '+drift+' saved/configured differences; '+
            invalid+' invalid stored formats. Unverified does not mean healthy.';
        target.appendChild(summary);
        const table=document.createElement('table');table.className='table';
        const header=document.createElement('tr');
        ['Group','Fields','Runtime observed','Differences','Invalid formats','Status']
            .forEach(v=>cell(header,v,'th'));
        table.appendChild(header);
        for (const group of GROUPS) {
            const r=result.find(x=>x.group.id===group.id);
            const tr=document.createElement('tr');
            cell(tr,group.label);
            cell(tr,r ? r.rows.length : 'Not verified');
            cell(tr,r ? r.totals.observed : 'Unknown');
            cell(tr,r ? r.totals.drift : 'Unknown');
            cell(tr,r ? r.totals.invalid : 'Unknown');
            cell(tr,r ? 'Read-only complete' : 'Readback unavailable');
            table.appendChild(tr);
        }
        target.appendChild(table);
        for (const r of result) {
            const details=document.createElement('details');
            const label=document.createElement('summary');
            label.textContent=r.group.label+' ('+r.rows.length+' fields)';
            details.appendChild(label);
            const rows=document.createElement('table');rows.className='table';
            const headings=document.createElement('tr');
            ['Setting ID','Verification status','Evidence scope']
                .forEach(v=>cell(headings,v,'th'));
            rows.appendChild(headings);
            for (const field of r.rows) {
                const tr=document.createElement('tr');
                cell(tr,field.id);cell(tr,field.state);cell(tr,field.source);
                rows.appendChild(tr);
            }
            details.appendChild(rows);target.appendChild(details);
        }
        const note=document.createElement('p');
        note.textContent='Read-only source observations, not hardware qualification. '+
            'PON O5.1 and 10G Ethernet do not establish Internet connectivity. '+
            'Saved values, addresses, identifiers and credentials are deliberately excluded.';
        target.appendChild(note);
        target.hidden=false;
        status.textContent=errors ?
            'Partial readback: '+errors+' groups unavailable. No settings changed.' :
            'All seven read-only groups checked. No settings changed.';
    }
    async function refresh() {
        const button=document.getElementById('aott-verification-refresh');
        const status=document.getElementById('aott-verification-status');
        const output=document.getElementById('aott-verification-results');
        if (busy || !button || !status || !output) return;
        busy=true;button.disabled=true;output.replaceChildren();output.hidden=true;
        status.textContent='Reading independent source groups. No settings will be changed.';
        const result=[];let errors=0;
        // Two bounded, authenticated read-only requests at a time limit
        // burden on the embedded device. No recurring timers or uploads.
        try {
            for (let i=0;i<GROUPS.length;i+=2) {
                const batch=GROUPS.slice(i,i+2);
                await Promise.all(batch.map(async group=>{
                    const url=verifiedPath(group);
                    if (!url) {errors++;return;}
                    const controller=new AbortController();
                    const timer=setTimeout(()=>controller.abort(),9000);
                    try {
                        const response=await request8311(url,{
                            method:'GET',cache:'no-store',signal:controller.signal
                        });
                        result.push(check(response,group));
                    } catch (_) {
                        // Do not reflect raw native errors or values.
                        errors++;
                    } finally {
                        clearTimeout(timer);
                    }
                }));
            }
            render(result,errors);
        } finally {
            busy=false;button.disabled=false;
        }
    }
    function bind() {
        const button=document.getElementById('aott-verification-refresh');
        if (button) button.addEventListener('click',refresh);
    }
    if (document.readyState==='loading') {
        document.addEventListener('DOMContentLoaded',bind,{once:true});
    } else bind();
})();
