"""Simple desktop interface for the local recording-to-text app."""
from pathlib import Path
import gc
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .review import clock
from .training_store import collect_example, collection_dir

BG = '#f4f7f3'
WHITE = '#ffffff'
INK = '#273a30'
MUTED = '#74867a'
GREEN = '#557d60'
PALE = '#eaf2e9'
FONT = '맑은 고딕'


def save_corrected(original: Path, content: str) -> Path:
    """Create a separate corrected TXT, never replacing the original or earlier edits."""
    if not content.strip():
        raise ValueError('저장할 내용이 없습니다.')
    for index in range(1, 10000):
        suffix = '' if index == 1 else f'-{index}'
        dest = original.with_name(original.stem + '.수정본' + suffix + '.txt')
        created = False
        try:
            with dest.open('x', encoding='utf-8-sig', newline='\n') as stream:
                created = True
                stream.write(content.rstrip() + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            return dest
        except FileExistsError:
            continue
        except BaseException:
            if created:
                dest.unlink(missing_ok=True)
            raise
    raise RuntimeError('같은 이름의 수정본이 너무 많습니다.')


def launch_gui(*, speed, validate_source, load_model, transcribe, speed_choices,
               needs_download=None, manifest=None):
    app = tk.Tk()
    app.title('녹음 파일 변환')
    app.geometry('1040x740')
    app.minsize(900, 680)
    app.configure(bg=BG)
    app.option_add('*Font', (FONT, 11))
    styles = ttk.Style(app)
    styles.theme_use('clam')
    styles.configure('Clean.Horizontal.TProgressbar', troughcolor='#e7eee6', background=GREEN,
                     bordercolor='#e7eee6', lightcolor=GREEN, darkcolor=GREEN, thickness=8)
    styles.configure('Clean.TCombobox', padding=7, arrowsize=14, fieldbackground='#f6f9f5')
    state = {'source': None, 'output': None, 'model': None, 'model_name': None,
             'requested_model': None, 'requested_speed': speed, 'busy': False, 'dirty': False, 'internal_edit': False}
    events = queue.Queue()
    chosen = tk.StringVar(value='선택된 파일 없음')
    detail = tk.StringVar(value='녹음 파일을 선택하세요.')
    status = tk.StringVar(value='파일을 선택해 주세요.')
    percent = tk.StringVar(value='대기 중')
    model_options = {'기본 모델 · small': 'small', '큰 모델 · turbo': 'turbo'}
    model_choice = tk.StringVar(value='기본 모델 · small')
    speed_choice = tk.StringVar(value=next(label for label, value in speed_choices.items() if value == speed))

    def label(parent, text='', **kw):
        return tk.Label(parent, text=text, bg=kw.pop('bg', WHITE), fg=kw.pop('fg', INK),
                        font=kw.pop('font', (FONT, 11)), **kw)

    def button(parent, text, command, primary=False, **kw):
        return tk.Button(parent, text=text, command=command, relief='flat', bd=0,
                         bg=GREEN if primary else PALE, fg='white' if primary else GREEN,
                         activebackground='#436a4d' if primary else '#dcebdc',
                         activeforeground='white' if primary else INK,
                         disabledforeground='#a7b5a8', font=(FONT, 11, 'bold'),
                         padx=18, pady=10, cursor='hand2', **kw)

    top = tk.Frame(app, bg=BG); top.pack(fill='x', padx=32, pady=(12, 0))
    label(top, '▥', bg=GREEN, fg='white', font=(FONT, 17, 'bold'), padx=11, pady=5).pack(side='left')
    brand = tk.Frame(top, bg=BG); brand.pack(side='left', padx=12)
    label(brand, '녹음 파일 변환', bg=BG, font=(FONT, 17, 'bold')).pack(anchor='w')
    label(brand, 'AUDIO TO TEXT', bg=BG, fg='#95a99a', font=(FONT, 8, 'bold')).pack(anchor='w')
    label(top, '●  이 PC에서 변환', bg=PALE, fg=GREEN, padx=12, pady=6, font=(FONT, 9, 'bold')).pack(side='right')
    intro = tk.Frame(app, bg=BG); intro.pack(fill='x', padx=34, pady=(12, 12))
    label(intro, '녹음 파일을 텍스트로 변환', bg=BG, font=(FONT, 20, 'bold')).pack(anchor='w')
    label(intro, '파일을 선택하고 변환을 시작하세요.',
          bg=BG, fg=MUTED, font=(FONT, 11)).pack(anchor='w', pady=(5, 0))
    label(app, '✳  변환 결과는 원본 녹음을 들으며 확인하세요.', bg=BG, fg=MUTED, font=(FONT, 10)).pack(side='bottom', anchor='w', padx=34, pady=(8, 10))
    body = tk.Frame(app, bg=BG); body.pack(fill='both', expand=True, padx=32)
    body.grid_columnconfigure(0, weight=4, uniform='col'); body.grid_columnconfigure(1, weight=6, uniform='col'); body.grid_rowconfigure(0, weight=1)
    left = tk.Frame(body, bg=WHITE, highlightbackground='#e5ece3', highlightthickness=1, padx=20, pady=14)
    right = tk.Frame(body, bg=WHITE, highlightbackground='#e5ece3', highlightthickness=1, padx=20, pady=14)
    left.grid(row=0, column=0, sticky='nsew', padx=(0, 9)); right.grid(row=0, column=1, sticky='nsew', padx=(9, 0))
    label(left, 'STEP 01', fg='#83a58b', font=(FONT, 9, 'bold')).pack(anchor='w')
    label(left, '녹음 파일 선택', font=(FONT, 17, 'bold')).pack(anchor='w', pady=(5, 0))
    label(left, '변환할 파일을 선택하세요.', fg=MUTED, font=(FONT, 10)).pack(anchor='w', pady=(3, 9))
    selection = tk.Frame(left, bg=WHITE); selection.pack(fill='x', pady=(3, 6))
    select_btn = button(selection, '＋  파일 선택', lambda: select())
    select_btn.pack(anchor='w')
    label(selection, textvariable=chosen, bg=WHITE, fg=MUTED, font=(FONT, 10),
          wraplength=300, justify='left', anchor='w').pack(fill='x', pady=(9, 0))
    settings = tk.Frame(left, bg=WHITE); settings.pack(fill='x', pady=(10, 0))
    label(settings, '음성 인식 모델', font=(FONT, 10, 'bold')).pack(anchor='w')
    model_box = ttk.Combobox(settings, textvariable=model_choice, values=list(model_options), state='readonly', style='Clean.TCombobox'); model_box.pack(fill='x', pady=(3, 6))
    label(settings, '처리 방식', font=(FONT, 10, 'bold')).pack(anchor='w')
    speed_box = ttk.Combobox(settings, textvariable=speed_choice, values=list(speed_choices), state='readonly', style='Clean.TCombobox'); speed_box.pack(fill='x', pady=(3, 0))
    label(left, '빠른 처리의 속도와 결과는 PC 환경에 따라 다를 수 있습니다.', fg=MUTED, font=(FONT, 9), wraplength=300, justify='left').pack(anchor='w', pady=(5, 3))
    run_btn = button(left, '텍스트로 변환  →', lambda: start(), primary=True, state='disabled'); run_btn.pack(fill='x', pady=(4, 0))
    label(right, 'STEP 02', fg='#83a58b', font=(FONT, 9, 'bold')).pack(anchor='w')
    label(right, '변환된 글', font=(FONT, 17, 'bold')).pack(anchor='w', pady=(5, 0))
    label(right, '변환 중 수정 · 수정본 저장 시 이 PC에 비교 자료 보관', fg=MUTED, font=(FONT, 10)).pack(anchor='w', pady=(4, 14))
    info = tk.Frame(right, bg=WHITE); info.pack(fill='x')
    label(info, textvariable=status, fg=GREEN, font=(FONT, 9), wraplength=390, justify='left').pack(side='left', fill='x', expand=True, anchor='w')
    label(info, textvariable=percent, fg=MUTED, font=(FONT, 9)).pack(side='right')
    bar = ttk.Progressbar(right, maximum=100, mode='determinate', style='Clean.Horizontal.TProgressbar'); bar.pack(fill='x', pady=(9, 15))
    text_frame = tk.Frame(right, bg='#f9fbf8', highlightbackground='#e9efe7', highlightthickness=1); text_frame.pack(fill='both', expand=True)
    text = tk.Text(text_frame, wrap='word', bg='#f9fbf8', fg=INK, bd=0, padx=15, pady=15,
                   font=(FONT, 11), height=8, width=20, spacing1=4, spacing3=9, state='disabled', undo=True)
    scroll = ttk.Scrollbar(text_frame, orient='vertical', command=text.yview); text.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y'); text.pack(side='left', fill='both', expand=True)
    actions = tk.Frame(right, bg=WHITE); actions.pack(fill='x', pady=(10, 0))
    folder_btn = button(actions, '저장 폴더 열기', lambda: os.startfile(str(state['output'].parent)), state='disabled'); folder_btn.pack(side='right')
    save_btn = button(actions, '수정본 저장', lambda: save_edit(), primary=True, state='disabled'); save_btn.pack(side='right', padx=(0, 8))

    def changed(event=None):
        if text.edit_modified():
            if not state['internal_edit']:
                state['dirty'] = True
            text.edit_modified(False)

    text.bind('<<Modified>>', changed)

    def write_preview(value, clear=False):
        state['internal_edit'] = True
        try:
            text.configure(state='normal')
            cursor = text.index('insert')
            view = text.yview()[0]
            if clear:
                text.delete('1.0', 'end')
            if value:
                text.insert('end', value)
            if state['dirty'] and not clear:
                text.mark_set('insert', cursor)
                text.yview_moveto(view)
            else:
                text.see('end')
            text.edit_modified(False)
            if clear:
                text.edit_reset()
        finally:
            state['internal_edit'] = False

    def discard_ok():
        return not state['dirty'] or messagebox.askyesno(
            '수정 내용 확인', '저장하지 않은 수정 내용이 있습니다. 계속하시겠습니까?', parent=app)

    def save_edit():
        if state['busy'] or state['output'] is None:
            return
        content = text.get('1.0', 'end-1c')
        if not content.strip():
            messagebox.showerror('수정본 저장', '저장할 내용이 없습니다.', parent=app)
            return
        try:
            dest = save_corrected(state['output'], content)
        except Exception as exc:
            messagebox.showerror('수정본 저장', str(exc), parent=app)
            return
        state['dirty'] = False
        state['busy'] = True
        for widget in (select_btn, run_btn, folder_btn, save_btn, model_box, speed_box):
            widget.configure(state='disabled')
        status.set('수정본 저장 완료 · 이 PC에 비교 자료 보관 중')
        audio, original = state['source'], state['output']

        def store():
            try:
                saved = collect_example(audio, original, dest)
                events.put(('collected', (dest, saved)))
            except Exception as exc:
                events.put(('collection_error', (dest, str(exc))))

        threading.Thread(target=store, daemon=True).start()

    def select():
        path = filedialog.askopenfilename(title='녹음 파일 선택', parent=app, filetypes=[('녹음 파일', '*.m4a *.mp3 *.wav *.amr *.3gp *.3ga *.aac *.ogg *.flac *.mp4'), ('모든 파일', '*.*')])
        if not path: return
        try: source = validate_source(Path(path))
        except Exception as exc:
            messagebox.showerror('파일 확인', str(exc), parent=app); return
        if not discard_ok(): return
        state['source'] = source; state['output'] = None; state['dirty'] = False
        chosen.set(source.name); detail.set('원본 녹음은 변경되지 않습니다.')
        status.set('파일 선택 완료 · 변환을 시작하세요.'); percent.set('대기 중')
        bar['value'] = 0; folder_btn.configure(state='disabled'); save_btn.configure(state='disabled'); run_btn.configure(state='normal'); write_preview('', clear=True); text.configure(state='disabled')

    def work():
        try:
            name = state['requested_model']
            if state['model'] is None or state['model_name'] != name:
                events.put(('status', '음성 인식 모델 준비 중'))
                state['model'] = None; gc.collect()
                state['model'] = load_model(name, lambda m: events.put(('status', m)))
                state['model_name'] = name
            events.put(('status', '변환 중 · 창을 닫지 마세요.'))
            output, seconds = transcribe(state['source'], state['model'], speed=state['requested_speed'],
                progress=lambda n: events.put(('progress', n)), on_segment=lambda row: events.put(('segment', row)))
            events.put(('done', (output, seconds)))
        except Exception as exc: events.put(('error', str(exc)))

    def start():
        if state['busy'] or state['source'] is None: return
        if not discard_ok(): return
        model = model_options[model_choice.get()]
        if needs_download and needs_download(model):
            size = sum(item['size'] for item in manifest[model]['files']) / 1e9
            if not messagebox.askyesno('모델 준비', f'처음 한 번 약 {size:.1f}GB 모델을 내려받습니다.\n인터넷 연결과 저장 공간이 필요합니다.\n녹음 파일은 업로드하지 않습니다.\n계속할까요?', parent=app): return
        state.update(busy=True, requested_model=model, requested_speed=speed_choices[speed_choice.get()], output=None)
        for widget in (select_btn, run_btn, folder_btn, save_btn, model_box, speed_box): widget.configure(state='disabled')
        state['dirty'] = False
        write_preview('', clear=True); bar['value'] = 0; percent.set('준비 중'); status.set('변환 준비 중')
        threading.Thread(target=work, daemon=True).start()

    def finish():
        state['busy'] = False
        select_btn.configure(state='normal'); run_btn.configure(state='normal')
        model_box.configure(state='readonly'); speed_box.configure(state='readonly')

    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == 'status': status.set(value)
                elif kind == 'progress': bar['value'] = value; percent.set(f'{int(value)}%')
                elif kind == 'segment': write_preview(f"[{clock(value['start'])}~{clock(value['end'])}] {value['text']}\n\n")
                elif kind == 'done':
                    output, seconds = value; state['output'] = output; finish(); folder_btn.configure(state='normal'); save_btn.configure(state='normal')
                    status.set(f'변환 완료 · {output.name}'); percent.set('완료')
                    status.set(f'원본 저장 완료 · 수정 후 수정본 저장을 누르세요.')
                elif kind == 'error': finish(); status.set('변환하지 못했습니다. 안내를 확인해 주세요.'); percent.set('중단'); messagebox.showerror('변환 확인', value, parent=app)
                elif kind == 'collected':
                    corrected, saved = value
                    finish(); folder_btn.configure(state='normal'); save_btn.configure(state='normal')
                    status.set('수정본 및 비교 자료 저장 완료')
                    messagebox.showinfo('저장 완료', f'수정본: {corrected}\n\n비교 자료: {saved}\n\n자료는 이 PC에만 저장됩니다. 모델은 자동 학습되지 않습니다.', parent=app)
                elif kind == 'collection_error':
                    corrected, reason = value
                    finish(); folder_btn.configure(state='normal'); save_btn.configure(state='normal')
                    status.set('수정본 저장됨 · 비교 자료 보관 실패')
                    messagebox.showerror('비교 자료 보관 실패', f'수정본은 저장됐습니다.\n{corrected}\n\n비교 자료를 보관하지 못했습니다: {reason}', parent=app)
        except queue.Empty: pass
        app.after(100, poll)

    def close():
        if state['busy'] and not messagebox.askyesno('변환 중', '지금 닫으면 변환이 중단됩니다. 창을 닫을까요?', parent=app): return
        if not discard_ok(): return
        app.destroy()
    app.protocol('WM_DELETE_WINDOW', close); poll(); app.mainloop()
