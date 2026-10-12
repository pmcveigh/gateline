for (const input of document.querySelectorAll('[data-filter-input]')) {
 const target=document.getElementById(input.dataset.filterInput);
 if(!target)continue;
 function filter(){const query=input.value.trim().toLocaleLowerCase();const rows=[...target.querySelectorAll('[data-filter-row]')];for(const row of rows)row.hidden=!row.textContent.toLocaleLowerCase().includes(query);const count=document.querySelector(`[data-filter-count="${input.dataset.filterInput}"]`);if(count)count.textContent=rows.filter(row=>!row.hidden).length;}
 input.addEventListener('input',filter);filter();
}
