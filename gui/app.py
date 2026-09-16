"""Tkinter desktop editor. CAD work runs off the Tk event thread."""
import copy
import json
import math
import os
from pathlib import Path
import queue
import threading
import tempfile
import logging
from logging.handlers import RotatingFileHandler
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from dataclasses import asdict,fields,replace
from core.dstv_writer import NC1Header,default_header_from_filename,write_nc1
from core.feature_extractor import Hole,Marking,ContourPoint,EndCut
from core.profiles import Profile,DSTV_CODE,load_profiles
from core.project import save_project,load_project
from core.validation import validate_features,finite
from core.preview import contour_xy,slot_xy
from core.recovery import RecoveryStore,user_data_dir
from core.diagnostics import diagnose
from core.version import VERSION
from core.stock_preview import face_span,end_outline

FACES=('v','o','u','h')
CONTOURS={'AK':'outer_contours','IK':'inner_contours','KO':'scribe_contours','PU':'powder_contours'}

class App:
    def __init__(self,root):
        self.root=root;root.title('STEP2NC1 | Structural part editor');root.geometry('1360x860');root.minsize(1050,680)
        self.fs=None;self.header=NC1Header();self.source='';self.project_path=None;self.dirty=False;self.syncing=False;self.busy=False
        self.jobs=queue.Queue();self.zoom=1.;self.pan=[0.,0.];self.profiles=load_profiles()
        self.cancel_event=threading.Event();self.closing=False;self.recovered_from=None
        self.recovery=None;self.log_path=None
        self.logger=logging.getLogger('step2nc1.'+str(id(self)));self.logger.setLevel(logging.INFO)
        self.logger.addHandler(logging.NullHandler())
        try:
            self.recovery=RecoveryStore()
            logs=user_data_dir()/'logs';logs.mkdir(parents=True,exist_ok=True)
            self.log_path=logs/f'application-{os.getpid()}.log'
            handler=RotatingFileHandler(self.log_path,maxBytes=1000000,backupCount=2,encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'));self.logger.addHandler(handler)
        except OSError as exc:
            root.after(200,lambda message=str(exc):messagebox.showwarning('Recovery or logging unavailable','Automatic recovery or diagnostic logging could not start. Save projects manually.\n'+message,parent=root))
        self._build();root.protocol('WM_DELETE_WINDOW',self.close)
        root.report_callback_exception=self.callback_error
        root.bind('<Control-o>',lambda e:self.open_file());root.bind('<Control-s>',lambda e:self.save())
        root.bind('<Control-e>',lambda e:self.export());root.after(100,self.poll)
        root.after(400,self.offer_recovery);root.after(30000,self.autosave)

    def _build(self):
        style=ttk.Style();style.theme_use('clam')
        style.configure('TButton',padding=(10,5));style.configure('Treeview',rowheight=25)
        bar=ttk.Frame(self.root,padding=8);bar.pack(fill='x')
        self.buttons=[]
        for text,cmd in [('Open',self.open_file),('Save project',self.save),('Export NC1',self.export),('Batch NC1',self.batch),('STEP to IGES',self.export_iges)]:
            b=ttk.Button(bar,text=text,command=cmd);b.pack(side='left',padx=3);self.buttons.append(b)
        self.cancel_button=ttk.Button(bar,text='Cancel',command=self.cancel_job,state='disabled');self.cancel_button.pack(side='left',padx=3)
        ttk.Button(bar,text='Recover draft',command=self.offer_recovery).pack(side='left',padx=3)
        ttk.Button(bar,text='Support report',command=self.support_report).pack(side='left',padx=3)
        self.title=ttk.Label(bar,text='Open STEP, NC1, or a saved project',font=('Segoe UI',11));self.title.pack(side='left',padx=15)
        panes=ttk.Panedwindow(self.root,orient='horizontal');panes.pack(fill='both',expand=True,padx=10)
        left=ttk.Frame(panes,width=290);panes.add(left,weight=0)
        scroll=tk.Canvas(left,highlightthickness=0,width=285);sb=ttk.Scrollbar(left,orient='vertical',command=scroll.yview)
        scroll.configure(yscrollcommand=sb.set);sb.pack(side='right',fill='y');scroll.pack(side='left',fill='both',expand=True)
        form=ttk.Frame(scroll,padding=10);window=scroll.create_window((0,0),window=form,anchor='nw')
        form.bind('<Configure>',lambda e:scroll.configure(scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>',lambda e:scroll.itemconfigure(window,width=e.width))
        self.vars={}
        row=0
        def title(text):
            nonlocal row
            ttk.Label(form,text=text,font=('Segoe UI',10,'bold')).grid(row=row,column=0,columnspan=2,sticky='w',pady=(14,6));row+=1
        def entry(label,key,value='',choices=None):
            nonlocal row
            ttk.Label(form,text=label).grid(row=row,column=0,sticky='w',pady=3)
            var=tk.StringVar(value=value);self.vars[key]=var
            w=ttk.Combobox(form,textvariable=var,values=choices,state='readonly',width=15) if choices else ttk.Entry(form,textvariable=var,width=18)
            w.grid(row=row,column=1,sticky='ew',pady=3);row+=1
            var.trace_add('write',self.changed)
            return w
        title('Section | dimensions in mm')
        entry('Family','family','W',['W','C','L','HSS','HSS_R','PLATE'])
        entry('Profile label','name')
        for label,key in [('Length','length'),('Depth / plate width','d'),('Width / plate thickness','bf'),('Flange thickness','tf'),('Web thickness','tw'),('Wall / angle thickness','t_wall'),('Root radius','k'),('Weight kg/m','weight'),('Paint m2/m','paint')]:entry(label,key,'0')
        ttk.Button(form,text='Choose catalog profile',command=self.choose_profile).grid(row=row,column=0,columnspan=2,sticky='ew',pady=6);row+=1
        title('Part information')
        for label,key in [('Order','order_number'),('Drawing','drawing_number'),('Phase','phase_number'),('Piece / mark','piece_number'),('Material grade','steel_quality'),('Quantity','quantity'),('Info 1','text_info_1'),('Info 2','text_info_2'),('Info 3','text_info_3'),('Info 4','text_info_4')]:entry(label,key)
        title('End miters | degrees')
        for label,key in [('Web start','web_start_deg'),('Web end','web_end_deg'),('Flange start','flange_start_deg'),('Flange end','flange_end_deg')]:entry(label,key,'0')
        title('STEP analysis')
        entry('Source length axis','axis','auto',['auto','x','y','z'])
        ttk.Button(form,text='Re-analyze STEP',command=self.redetect).grid(row=row,column=0,columnspan=2,sticky='ew',pady=4);row+=1
        ttk.Button(form,text='Apply edits / refresh',command=self.apply).grid(row=row,column=0,columnspan=2,sticky='ew',pady=4)
        right=ttk.Frame(panes);panes.add(right,weight=1)
        viewbar=ttk.Frame(right,padding=5);viewbar.pack(fill='x')
        ttk.Label(viewbar,text='Face').pack(side='left');self.face=tk.StringVar(value='v')
        self.face_buttons={}
        for face,label in [('v','v | front'),('o','o | top'),('u','u | bottom'),('h','h | back')]:
            button=ttk.Radiobutton(viewbar,text=label,value=face,variable=self.face,command=self.fit)
            button.pack(side='left',padx=4);self.face_buttons[face]=button
        ttk.Button(viewbar,text='Fit',command=self.fit).pack(side='right')
        ttk.Label(viewbar,text='Wheel: zoom  |  Drag: pan').pack(side='right',padx=10)
        self.canvas=tk.Canvas(right,bg='#111923',highlightthickness=0,height=340);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.draw());self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Button-4>',lambda e:self.wheel(e,1));self.canvas.bind('<Button-5>',lambda e:self.wheel(e,-1))
        self.canvas.bind('<ButtonPress-1>',self.pan_start);self.canvas.bind('<B1-Motion>',self.pan_move)
        self.tabs=ttk.Notebook(right);self.tabs.pack(fill='both',expand=True,pady=5)
        self.trees={}
        specs=[('Holes',('face','x','y','diameter','operation'),self.add_hole,self.edit_hole,self.delete_hole),
               ('Contours',('block','face','points','arcs','bevels','extent'),self.add_contour,self.edit_contour,self.delete_contour),
               ('Markings',('face','x','y','height','text'),self.add_mark,self.edit_mark,self.delete_mark)]
        for name,cols,add,edit,delete in specs:
            f=ttk.Frame(self.tabs);self.tabs.add(f,text=name)
            controls=ttk.Frame(f);controls.pack(fill='x')
            for label,cmd in [('Add',add),('Edit',edit),('Delete',delete)]:ttk.Button(controls,text=label,command=cmd).pack(side='left',padx=3,pady=4)
            tree=ttk.Treeview(f,columns=cols,show='headings',height=8,selectmode='browse');self.trees[name]=tree
            for col in cols:tree.heading(col,text=col.title());tree.column(col,width=100,stretch=True)
            sb=ttk.Scrollbar(f,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=sb.set);sb.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
            tree.bind('<Double-1>',lambda e,cmd=edit:cmd())
        f=ttk.Frame(self.tabs);self.tabs.add(f,text='Review / diagnostics')
        self.review=tk.Text(f,height=9,wrap='word',font=('Consolas',10));self.review.pack(fill='both',expand=True)
        self.status=tk.StringVar(value='Ready. Geometry and NC1 coordinates use millimetres.')
        ttk.Label(self.root,textvariable=self.status,padding=(12,7)).pack(fill='x')

    def changed(self,*_):
        if self.fs and not self.syncing:self.dirty=True;self.root.title('STEP2NC1 | Unsaved changes')

    def confirm_discard(self):
        return not self.dirty or messagebox.askyesno('Unsaved changes','Discard the unsaved project changes?',parent=self.root)

    def close(self):
        if self.busy:
            if messagebox.askyesno('Cancel and close','Cancel the current operation and close the application?',parent=self.root):
                if not self.confirm_discard():return
                self.closing=True;self.cancel_job()
            return
        if self.confirm_discard():self.finish_close()

    def finish_close(self):
        if self.recovery:
            if self.recovered_from:self.recovery.discard_path(self.recovered_from)
            self.recovery.close(discard=True)
        for handler in self.logger.handlers[:]:
            handler.close();self.logger.removeHandler(handler)
        self.root.destroy()

    def cancel_job(self):
        self.cancel_event.set();self.status.set('Cancelling the current operation...')

    def callback_error(self,kind,value,tb):
        self.logger.error('Interface error',exc_info=(kind,value,tb))
        messagebox.showerror('Action could not be completed',str(value)+'\nUse Support report to save diagnostic information.',parent=self.root)

    def autosave(self):
        if self.recovery and self.fs and self.dirty and not self.busy:
            try:self.recovery.save(self.fs,self.header,self.source,{k:v.get() for k,v in self.vars.items()})
            except Exception:
                self.logger.exception('Automatic recovery save failed')
                self.status.set('Draft recovery could not be saved. Use Save project.')
        self.root.after(30000,self.autosave)

    def offer_recovery(self):
        if self.busy or not self.recovery:return
        candidates=self.recovery.available()
        if not candidates:return
        path,data=candidates[0]
        label=Path(data.get('source','')).name or path.name
        if not messagebox.askyesno('Recover unsaved work',f'Recover the latest unsaved draft for {label}?',parent=self.root):return
        if not self.confirm_discard():return
        try:
            self.loaded((*load_project(path),None));self.recovered_from=path
            for key,value in data.get('recovery',{}).get('form',{}).items():
                if key in self.vars:self.vars[key].set(value)
            self.dirty=True;self.status.set('Recovered draft. Review the fields and save the project.')
        except Exception as exc:messagebox.showerror('Recovery failed',str(exc),parent=self.root)

    def support_report(self):
        from core.support import write_support_bundle
        path=filedialog.asksaveasfilename(defaultextension='.zip',initialfile='step2nc1-support.zip',filetypes=[('Support report','*.zip')])
        if not path:return
        try:
            write_support_bundle(path,{'errors':self.fs.errors if self.fs else [],'warnings':self.fs.warnings if self.fs else [],'version':VERSION},self.log_path)
            self.status.set('Support report saved: '+path)
        except Exception as exc:messagebox.showerror('Support report failed',str(exc),parent=self.root)

    def run_job(self,func,done,show_cancelled=False):
        if self.busy:return
        self.show_cancelled_result=show_cancelled
        self.cancel_event.clear()
        self.busy=True;self.status.set('Analyzing geometry...')
        self.cancel_button.configure(state='normal')
        self.disabled_widgets=[]
        def disable(widget):
            for child in widget.winfo_children():
                if child is not self.cancel_button and isinstance(child,(ttk.Entry,ttk.Combobox,ttk.Button,ttk.Treeview)):
                    if 'disabled' not in child.state():self.disabled_widgets.append(child);child.state(['disabled'])
                disable(child)
        disable(self.root)
        def worker():
            try:self.jobs.put((done,func(),None))
            except Exception as exc:self.jobs.put((done,None,exc))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        try:
            done,result,error=self.jobs.get_nowait();self.busy=False
            self.cancel_button.configure(state='disabled')
            for widget in self.disabled_widgets:
                if widget.winfo_exists():widget.state(['!disabled'])
            if self.closing:self.finish_close();return
            if self.cancel_event.is_set():
                self.status.set('Operation cancelled. Completed batch files remain in the output folder.')
                if self.show_cancelled_result and not error:done(result)
            elif error:
                self.logger.error('Operation failed: %s\n%s',error,getattr(error,'technical_detail',''))
                d=diagnose(error);messagebox.showerror(d['summary'],d['detail']+'\n\n'+d['action'],parent=self.root);self.status.set(d['summary'])
            else:done(result)
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def open_file(self):
        if self.busy or not self.confirm_discard():return
        path=filedialog.askopenfilename(filetypes=[('STEP / NC1 / Project','*.step *.stp *.STEP *.STP *.nc1 *.NC1 *.json'),('All files','*.*')])
        if not path:return
        axis=self.vars['axis'].get()
        def read():
            if path.lower().endswith('.json'):return (*load_project(path),path)
            if path.lower().endswith('.nc1'):
                from core.dstv_reader import read_nc1
                d=read_nc1(path);return d.features,d.header,path,None
            return (*self.analyze(path,axis,self.cancel_event),None)
        self.run_job(read,self.loaded)

    @staticmethod
    def analyze(path,axis,cancel_event=None):
        from core.conversion import isolated_convert,ConversionError
        with tempfile.TemporaryDirectory(prefix='step2nc1-') as directory:
            out=Path(directory)/'part.nc1'
            result=isolated_convert(path,out,length_axis=axis,project=True,cancel_event=cancel_event)
            if result.get('status')=='cancelled':raise ValueError('Conversion cancelled.')
            draft=out.with_suffix('.step2nc.json')
            if not draft.exists():raise ConversionError(result)
            return load_project(draft)

    def loaded(self,result):
        if self.recovery:
            self.recovery.clear()
            if self.recovered_from:self.recovery.discard_path(self.recovered_from);self.recovered_from=None
        self.fs,self.header,self.source,self.project_path=result
        self.dirty=False;self.sync_form();self.refresh();self.fit()
        self.title.configure(text=Path(self.source or self.project_path or '').name)
        self.root.title('STEP2NC1 | '+Path(self.source or '').name)
        self.status.set(f'{self.fs.section.profile.name} | {len(self.fs.holes)} holes | {len(self.fs.all_outer_contours())} outer contours | {len(self.fs.errors)} analysis issues')
        if self.fs.errors:self.tabs.select(3)

    def sync_form(self):
        if not self.fs:return
        self.syncing=True;p=self.fs.section.profile
        values={**asdict(self.header),**asdict(self.fs.end_cuts),'family':p.family,'name':p.name,'length':self.fs.section.length_in*25.4,
                'weight':p.kg_per_m,'paint':self.fs.section.paint_per_m}
        for key in ('d','bf','tf','tw','t_wall','k'):values[key]=getattr(p,key)*25.4
        for key,v in values.items():
            if key in self.vars:self.vars[key].set(f'{v:.5f}' if isinstance(v,float) else str(v))
        self.syncing=False

    def pull(self):
        if not self.fs:raise ValueError('Open a part first.')
        fs=copy.deepcopy(self.fs);p=fs.section.profile
        def number(key):
            value=float(self.vars[key].get() or '0');finite(value,key);return value
        for key in ('d','bf','tf','tw','t_wall','k'):setattr(p,key,number(key)/25.4)
        p.family=self.vars['family'].get();p.dstv_code=DSTV_CODE[p.family];p.name=self.vars['name'].get()
        p.weight_per_ft=number('weight')/1.48816394
        fs.section.family=p.family;fs.section.length_in=number('length')/25.4;fs.section.paint_per_m=number('paint')
        fs.end_cuts=EndCut(**{k:number(k) for k in asdict(fs.end_cuts)})
        header=copy.deepcopy(self.header)
        for k in asdict(header):
            if k in self.vars:setattr(header,k,int(self.vars[k].get()) if k=='quantity' else self.vars[k].get())
        header.profile_name=p.name;header.profile_code=p.dstv_code;header.weight_per_m=None;header.paint_per_m=None
        if min(fs.section.length_in,p.d,p.bf)<=0:raise ValueError('Length, depth and width must be positive.')
        self.fs,self.header=fs,header

    def apply(self):
        try:self.pull();self.refresh();self.draw();return True
        except Exception as exc:messagebox.showerror('Invalid input',str(exc),parent=self.root)

    def save(self):
        if self.busy:return
        try:
            self.pull()
            path=self.project_path or filedialog.asksaveasfilename(defaultextension='.step2nc.json',initialfile=Path(self.source).stem+'.step2nc.json',filetypes=[('STEP2NC1 project','*.step2nc.json')])
            if not path:return
            save_project(path,self.fs,self.header,self.source);self.project_path=path;self.dirty=False
            if self.recovery:
                self.recovery.clear()
                if self.recovered_from:self.recovery.discard_path(self.recovered_from);self.recovered_from=None
            self.root.title('STEP2NC1 | '+Path(path).name);self.status.set('Project saved: '+path)
        except Exception as exc:messagebox.showerror('Save failed',str(exc),parent=self.root)

    def export(self):
        if self.busy:return
        try:
            self.pull();validate_features(self.fs,self.header)
            path=filedialog.asksaveasfilename(defaultextension='.nc1',initialfile=Path(self.source).stem+'.nc1',filetypes=[('DSTV NC1','*.nc1')])
            if path:
                if Path(path).resolve()==Path(self.source).resolve() and not messagebox.askyesno('Replace input NC1','Replace the original NC1 with these edits?',parent=self.root):return
                write_nc1(self.fs,path,self.header,self.source);self.status.set('NC1 exported: '+path)
        except Exception as exc:messagebox.showerror('Export needs attention',str(exc),parent=self.root);self.tabs.select(3)

    def redetect(self):
        if self.busy or not self.source.lower().endswith(('.step','.stp')):return
        if not self.confirm_discard():return
        path=self.source;axis=self.vars['axis'].get()
        self.run_job(lambda:(*self.analyze(path,axis,self.cancel_event),None),self.loaded)

    def export_iges(self):
        if self.busy:return
        paths=filedialog.askopenfilenames(title='Select original STEP models for IGES export',filetypes=[('STEP','*.step *.stp *.STEP *.STP')])
        if not paths:return
        output=filedialog.askdirectory(title='Save IGES geometry files')
        if not output:return
        from main import cli_convert
        report=Path(output)/'iges-report.json'
        self.run_job(lambda:cli_convert(paths,output,report=report,cancel_event=self.cancel_event,output_format='iges'),
                     lambda result:self.batch_results(report),show_cancelled=True)

    def batch(self):
        if self.busy:return
        paths=filedialog.askopenfilenames(filetypes=[('STEP','*.step *.stp *.STEP *.STP')])
        if not paths:return
        output=filedialog.askdirectory(title='Choose output directory')
        if not output:return
        material=simpledialog.askstring('Batch material grade','Material grade for every selected part.\nLeave blank to keep the grade unspecified.',initialvalue='',parent=self.root)
        if material is None:return
        from main import cli_convert
        report=Path(output)/'batch-report.json'
        self.run_job(lambda:cli_convert(paths,output,material=material or None,project=True,report=report,cancel_event=self.cancel_event),
                     lambda result:self.batch_results(report),show_cancelled=True)

    def batch_results(self,path):
        data=json.loads(Path(path).read_text('utf-8'));rows=data['results']
        top=tk.Toplevel(self.root);top.title('Batch results');top.geometry('980x520');top.transient(self.root)
        summary=f"{data['converted']} exported / {data.get('requested',data['total'])} requested."
        if data.get('cancelled'):summary+=' Batch cancelled.'
        ttk.Label(top,text=summary,padding=10).pack(anchor='w');self.status.set(summary)
        frame=ttk.Frame(top);frame.pack(fill='both',expand=True,padx=10)
        tree=ttk.Treeview(frame,columns=('file','status','issue'),show='headings',height=12)
        for column,width in [('file',260),('status',90),('issue',540)]:tree.heading(column,text=column.title());tree.column(column,width=width)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
        tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y')
        tree.pack(side='left',fill='both',expand=True)
        detail=tk.Text(top,height=6,wrap='word');detail.pack(fill='x',padx=10,pady=6)
        for i,row in enumerate(rows):
            issue=row.get('diagnostic') or (diagnose(row.get('error','')) if row['status']!='ok' else {})
            tree.insert('','end',iid=str(i),values=(Path(row['source']).name,row['status'],issue.get('summary','')))
        def selected():
            ids=tree.selection();return rows[int(ids[0])] if ids else None
        def show(_=None):
            row=selected()
            if not row:return
            info=row.get('diagnostic') or diagnose(row.get('error',''))
            text=row['source']+'\n'+('Exported: '+str(row.get('output','')) if row['status']=='ok' else info['detail']+'\n\nNext step: '+info['action'])
            detail.configure(state='normal');detail.delete('1.0','end');detail.insert('1.0',text);detail.configure(state='disabled')
        def review():
            row=selected()
            draft=Path(row['output']).with_suffix('.step2nc.json') if row and row.get('output') else None
            if not draft or not draft.is_file():messagebox.showinfo('No draft','Section analysis did not produce an editable draft for this file.',parent=top);return
            if self.confirm_discard():self.loaded((*load_project(draft),str(draft)));top.destroy()
        tree.bind('<<TreeviewSelect>>',show)
        if data.get('format','nc1')=='nc1':
            ttk.Button(top,text='Review selected draft',command=review).pack(side='left',padx=10,pady=8)
        else:ttk.Label(top,text='IGES contains the original STEP geometry. NC1 editor changes are not included.').pack(side='left',padx=10,pady=8)
        ttk.Button(top,text='Close',command=top.destroy).pack(side='right',padx=10,pady=8)

    def choose_profile(self):
        if not self.fs:return
        top=tk.Toplevel(self.root);top.title('Catalog profile');top.transient(self.root);top.grab_set()
        family=self.vars['family'].get();lookup={p.name:p for p in self.profiles if p.family==family}
        var=tk.StringVar();box=ttk.Combobox(top,textvariable=var,values=sorted(lookup),width=30,state='readonly');box.pack(padx=15,pady=15)
        def choose():
            if var.get() not in lookup:return
            p=lookup[var.get()]
            self.vars['name'].set(p.name)
            for k in ('d','bf','tf','tw','t_wall','k'):self.vars[k].set(f'{getattr(p,k)*25.4:.5f}')
            self.vars['weight'].set(f'{p.kg_per_m:.5f}');top.destroy()
        ttk.Label(top,text='Selecting a profile changes dimensions.\nFeature coordinates stay in millimetres.').pack(padx=15)
        ttk.Button(top,text='Use profile',command=choose).pack(pady=15)

    def selected(self,name):
        if self.busy:return None
        selected=self.trees[name].selection();return int(selected[0]) if selected else None

    def refresh(self):
        if not self.fs:return
        for tree in self.trees.values():tree.delete(*tree.get_children())
        for i,h in enumerate(self.fs.holes):self.trees['Holes'].insert('','end',iid=str(i),values=(h.surface,f'{h.x_mm:.3f}',f'{h.y_mm:.3f}',f'{h.diameter_mm:.3f}','slot' if h.slotted else h.operation or 'through'))
        self.contour_index=[]
        if self.fs.outer_contour:
            self.fs.outer_contours.insert(0,self.fs.outer_contour);self.fs.outer_contour=[]
        for code,attr in CONTOURS.items():
            for j,c in enumerate(getattr(self.fs,attr)):
                i=len(self.contour_index);self.contour_index.append((code,j))
                self.trees['Contours'].insert('','end',iid=str(i),values=(code,c[0].surface,len(c),sum(abs(p.radius_mm)>0 for p in c),sum(bool(p.bevel_angle_1 or p.bevel_angle_2) for p in c[:-1]),f'{min(p.x_mm for p in c):.2f} - {max(p.x_mm for p in c):.2f} mm'))
        for i,m in enumerate(self.fs.markings):self.trees['Markings'].insert('','end',iid=str(i),values=(m.surface,f'{m.x_mm:.3f}',f'{m.y_mm:.3f}',m.height_mm,m.text or '(point mark)'))
        issues=[]
        try:validate_features(self.fs,self.header)
        except ValueError as exc:issues.append(str(exc))
        lines=['EXPORT STATUS: '+('Needs attention' if issues else 'Geometry checks passed'),*issues,*self.fs.warnings,
               '',self.fs.section.notes,'Material: '+(self.header.steel_quality or 'Not specified. Enter the grade before production use.'),
               'Filename quantity: '+str(self.header.quantity),'',
               'Preview: X = length. v/h ordinate = section depth. o/u ordinate = section width.',
               'Beveled contours show the outer material envelope. Edit a contour to review its signed bevel angles and depths.',
               'No controller postprocessor has been certified. Review the NC1 in your machine software.',
               '', 'Source-to-part transform (mm):',json.dumps(self.fs.section.frame,indent=2)]
        self.review.configure(state='normal');self.review.delete('1.0','end');self.review.insert('1.0','\n'.join(lines));self.review.configure(state='disabled')

    def edit_object(self,kind,index=None):
        if self.busy or not self.fs:return
        if not self.apply():return
        items=self.fs.holes if kind=='Hole' else self.fs.markings
        default=Hole(self.face.get(),0,0,20) if kind=='Hole' else Marking(self.face.get(),0,0,text='PART')
        obj=copy.deepcopy(items[index]) if index is not None else default
        dlg=RecordDialog(self.root,kind,obj);self.root.wait_window(dlg.top)
        if dlg.result:
            if index is None:items.append(dlg.result)
            else:items[index]=dlg.result
            self.changed();self.refresh();self.draw()

    def add_hole(self):self.edit_object('Hole')
    def edit_hole(self):
        i=self.selected('Holes')
        if i is not None:self.edit_object('Hole',i)
    def delete_hole(self):self.delete_object('Holes','holes')
    def add_mark(self):self.edit_object('Marking')
    def edit_mark(self):
        i=self.selected('Markings')
        if i is not None:self.edit_object('Marking',i)
    def delete_mark(self):self.delete_object('Markings','markings')
    def delete_object(self,tab,attr):
        if self.busy or not self.fs:return
        i=self.selected(tab)
        if i is not None:del getattr(self.fs,attr)[i];self.changed();self.refresh();self.draw()

    def add_contour(self):self.contour_dialog()
    def edit_contour(self):
        i=self.selected('Contours')
        if i is not None:self.contour_dialog(self.contour_index[i])
    def delete_contour(self):
        if self.busy:return
        i=self.selected('Contours')
        if i is not None:
            code,j=self.contour_index[i];del getattr(self.fs,CONTOURS[code])[j];self.changed();self.refresh();self.draw()
    def contour_dialog(self,entry=None):
        if self.busy or not self.fs:return
        code,index=entry if entry else ('IK',None)
        old=getattr(self.fs,CONTOURS[code])[index] if entry else []
        dlg=ContourDialog(self.root,code,old,self.face.get());self.root.wait_window(dlg.top)
        if dlg.result:
            new_code,points=dlg.result
            if entry:del getattr(self.fs,CONTOURS[code])[index]
            getattr(self.fs,CONTOURS[new_code]).append(points);self.changed();self.refresh();self.draw()

    def fit(self):self.zoom=1.;self.pan=[0.,0.];self.draw()
    def wheel(self,e,direction=None):
        old=self.zoom;self.zoom=min(80.,max(.25,self.zoom*(1.2 if (direction or e.delta)>0 else 1/1.2)))
        factor=self.zoom/old;cx=self.canvas.winfo_width()/2;cy=self.canvas.winfo_height()/2
        self.pan=[(self.pan[0]+cx-e.x)*factor-cx+e.x,(self.pan[1]+cy-e.y)*factor-cy+e.y];self.draw()
    def pan_start(self,e):self.drag=(e.x,e.y)
    def pan_move(self,e):
        self.pan[0]+=e.x-self.drag[0];self.pan[1]+=e.y-self.drag[1];self.drag=(e.x,e.y);self.draw()

    def draw(self):
        c=self.canvas;c.delete('all');cw=max(c.winfo_width(),100);ch=max(c.winfo_height(),100)
        if not self.fs:c.create_text(cw/2,ch/2,text='Open a structural part to begin',fill='#91a7bf',font=('Segoe UI',15));return
        sec=self.fs.section;face=self.face.get()
        for code,button in self.face_buttons.items():button.configure(state='disabled' if sec.family=='HSS_R' and code!='v' else 'normal')
        self.face_buttons['v'].configure(text='v | unrolled pipe' if sec.family=='HSS_R' else 'v | front')
        if sec.family=='HSS_R' and face!='v':self.face.set('v');face='v'
        L=sec.length_in*25.4;D=face_span(sec,face)
        if not all(math.isfinite(value) and value>0 for value in (L,D)):
            c.create_text(cw/2,ch/2,text='Correct the part dimensions to display a preview.',fill='#ffca70');return
        scale=min((cw-70)/L,(ch-70)/D)*self.zoom;ox=(cw-L*scale)/2+self.pan[0];oy=(ch+D*scale)/2+self.pan[1]
        def xy(x,y):return (ox+x*scale,oy-y*scale)
        def line(points,color,width=2):
            if len(points)>1:c.create_line(*[v for x,y in points for v in xy(x,y)],fill=color,width=width)
        c.create_rectangle(*xy(0,0),*xy(L,D),outline='#304253',dash=(4,4))
        if not any(points and points[0].surface==face for points in self.fs.all_outer_contours()):
            line(end_outline(sec,self.fs.end_cuts,face),'#6dc5e8')
        for code,attr in CONTOURS.items():
            for points in getattr(self.fs,attr):
                if points and points[0].surface==face:line(contour_xy(points),{'AK':'#6dc5e8','IK':'#ffca70','KO':'#b391ff','PU':'#82ddb4'}[code])
        for h in self.fs.holes:
            if h.surface!=face:continue
            if h.slotted:line(slot_xy(h),'#ffca70');continue
            x,y=xy(h.x_mm,h.y_mm);r=max(h.diameter_mm/2*scale,2)
            c.create_oval(x-r,y-r,x+r,y+r,outline='#ffca70',width=2)
        for m in self.fs.markings:
            if m.surface==face:c.create_text(*xy(m.x_mm,m.y_mm),text=m.text or '+',fill='#a3dfac',anchor='sw',angle=m.angle_deg,font=('Segoe UI',max(7,min(40,round(m.height_mm*scale)))))
        c.create_text(12,12,text=f'{face}  |  {L:.3f} x {D:.3f} mm   |   {sec.profile.name}',fill='#d3e4f2',anchor='nw',font=('Segoe UI',10))
        c.create_text(12,ch-15,text='Cyan: outside envelope   Amber: holes / cutouts   Violet: scribe   Green: marks',fill='#91a7bf',anchor='w')


class RecordDialog:
    def __init__(self,parent,kind,obj):
        self.result=None;self.obj=obj;self.vars={};self.top=tk.Toplevel(parent);self.top.title('Edit '+kind);self.top.transient(parent);self.top.grab_set()
        f=ttk.Frame(self.top,padding=16);f.pack()
        allowed=(['surface','x_mm','y_mm','diameter_mm','slotted','slot_length_mm','slot_angle_deg','operation','depth_mm','reference'] if kind=='Hole' else ['surface','x_mm','y_mm','angle_deg','height_mm','text','reference','mode'])
        for i,key in enumerate(allowed):
            ttk.Label(f,text=key.replace('_',' ').title()).grid(row=i,column=0,sticky='w',padx=6,pady=4)
            value=getattr(obj,key);var=tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value=str(value));self.vars[key]=var
            choices={'surface':FACES,'operation':('','m','g','l','s'),'reference':('u','s','o'),'mode':('','r','z')}.get(key)
            if isinstance(value,bool):w=ttk.Checkbutton(f,variable=var)
            elif choices:w=ttk.Combobox(f,textvariable=var,values=choices,state='readonly')
            else:w=ttk.Entry(f,textvariable=var,width=30)
            w.grid(row=i,column=1,pady=4)
        ttk.Button(f,text='Save feature',command=self.ok).grid(row=len(allowed),column=1,sticky='e',pady=10)
    def ok(self):
        try:
            data=asdict(self.obj)
            for k,v in self.vars.items():
                old=getattr(self.obj,k);value=v.get()
                if isinstance(old,(float,int)) and not isinstance(old,bool):value=float(value);finite(value,k)
                data[k]=value
            if 'diameter_mm' in data and (data['diameter_mm']<0 or data['depth_mm']<0):raise ValueError('Diameter and depth cannot be negative.')
            if data.get('slotted') and data['slot_length_mm']<data['diameter_mm']:raise ValueError('Slot overall length cannot be smaller than its diameter.')
            self.result=type(self.obj)(**data);self.top.destroy()
        except Exception as exc:messagebox.showerror('Invalid feature',str(exc),parent=self.top)


class ContourDialog:
    def __init__(self,parent,code,points,face):
        self.result=None;self.old=points;self.top=tk.Toplevel(parent);self.top.title('Contour editor');self.top.geometry('850x560');self.top.transient(parent);self.top.grab_set()
        bar=ttk.Frame(self.top,padding=10);bar.pack(fill='x')
        self.code=tk.StringVar(value=code);self.face=tk.StringVar(value=points[0].surface if points else face)
        for label,var,values in [('Block',self.code,tuple(CONTOURS)),('Face',self.face,FACES)]:
            ttk.Label(bar,text=label).pack(side='left',padx=5);ttk.Combobox(bar,textvariable=var,values=values,width=6,state='readonly').pack(side='left')
        ttk.Label(self.top,text='One point per line: X  Y  radius  bevel-angle-1  bevel-depth-1  bevel-angle-2  bevel-depth-2\nAll lengths in mm. Radius is for the outgoing arc. Positive = counterclockwise.\nOptional suffixes: reference=u/o/s  modifier=t/w. AK/IK must return to the first point.',padding=10).pack(fill='x')
        self.text=tk.Text(self.top,font=('Consolas',11),wrap='none');self.text.pack(fill='both',expand=True,padx=10)
        for p in points:self.text.insert('end',' '.join(f'{getattr(p,k):.5f}' for k in ('x_mm','y_mm','radius_mm','bevel_angle_1','bevel_depth_1','bevel_angle_2','bevel_depth_2'))+f' reference={p.reference}'+(f' modifier={p.modifier}' if p.modifier else '')+'\n')
        controls=ttk.Frame(self.top,padding=10);controls.pack(fill='x')
        ttk.Button(controls,text='Close contour',command=self.close_loop).pack(side='left');ttk.Button(controls,text='Save contour',command=self.ok).pack(side='right')
    def close_loop(self):
        lines=[s for s in self.text.get('1.0','end').splitlines() if s.strip()]
        if lines:self.text.insert('end',lines[0]+'\n')
    def ok(self):
        try:
            points=[]
            for line in self.text.get('1.0','end').splitlines():
                if not line.strip():continue
                numbers=[];options={}
                for token in line.replace(',',' ').split():
                    if '=' in token:
                        k,v=token.split('=',1)
                        if k not in ('reference','modifier'):raise ValueError('Unknown option: '+k)
                        options[k]=v
                    else:numbers.append(float(token))
                if not 2<=len(numbers)<=7:raise ValueError('Each row needs 2 to 7 numbers.')
                for n in numbers:finite(n,'Coordinate')
                numbers += [0.]*(7-len(numbers))
                points.append(ContourPoint(self.face.get(),*numbers[:3],options.get('reference','u'),options.get('modifier',''),*numbers[3:]))
            if len(points)<2:raise ValueError('Enter at least two points.')
            if self.code.get() in ('AK','IK') and (len(points)<3 or math.hypot(points[0].x_mm-points[-1].x_mm,points[0].y_mm-points[-1].y_mm)>.025):raise ValueError('Close the contour before saving.')
            self.result=(self.code.get(),points);self.top.destroy()
        except Exception as exc:messagebox.showerror('Invalid contour',str(exc),parent=self.top)


def main():
    root=tk.Tk();App(root);root.mainloop()

if __name__=='__main__':main()
