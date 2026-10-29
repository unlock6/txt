"""Simple desktop interface for the local recording-to-text app."""
from pathlib import Path
import gc
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .review import clock

BG = '#f4f7f3'
WHITE = '#ffffff'
INK = '#273a30'
MUTED = '#74867a'
GREEN = '#557d60'
PALE = '#eaf2e9'
FONT = '맑은 고딕'


def launch_gui(*, speed, validate_source, load_model, transcribe, speed_choices,
               needs_download=None, manifest=None):
    app = tk.Tk()
    app.title('말을 글로 | 녹음 문자 변환')
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
             'requested_model': None, 'requested_speed': speed, 'busy': False}
    events = queue.Queue()
    chosen = tk.StringVar(value='아직 선택한 파일이 없어요')
    detail = tk.StringVar(value='녹음 파일을 선택해 주세요.')
    status = tk.StringVar(value='녹음 파일을 선택하면 변환을 시작할 수 있어요.')
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
    label(brand, '말을 글로', bg=BG, font=(FONT, 17, 'bold')).pack(anchor='w')
    label(brand, 'VOICE TO TEXT', bg=BG, fg='#95a99a', font=(FONT, 8, 'bold')).pack(anchor='w')
    label(top, '●  내 PC에서 안전하게 처리', bg=PALE, fg=GREEN, padx=12, pady=6, font=(FONT, 9, 'bold')).pack(side='right')
    intro = tk.Frame(app, bg=BG); intro.pack(fill='x', padx=34, pady=(12, 12))
    label(intro, '목소리를 글로, 대화는 그대로.', bg=BG, font=(FONT, 20, 'bold')).pack(anchor='w')
    label(intro, '녹음 파일을 선택하면 글로 옮겨드려요. 변환된 글은 녹음과 함께 확인해 주세요.',
          bg=BG, fg=MUTED, font=(FONT, 11)).pack(anchor='w', pady=(5, 0))
    label(app, '✳  변환 결과에는 틀린 부분이 있을 수 있어요. 원래 녹음을 들으며 확인해 주세요.', bg=BG, fg=MUTED, font=(FONT, 10)).pack(side='bottom', anchor='w', padx=34, pady=(8, 10))
    body = tk.Frame(app, bg=BG); body.pack(fill='both', expand=True, padx=32)
    body.grid_columnconfigure(0, weight=4, uniform='col'); body.grid_columnconfigure(1, weight=6, uniform='col'); body.grid_rowconfigure(0, weight=1)
    left = tk.Frame(body, bg=WHITE, highlightbackground='#e5ece3', highlightthickness=1, padx=20, pady=14)
    right = tk.Frame(body, bg=WHITE, highlightbackground='#e5ece3', highlightthickness=1, padx=20, pady=14)
    left.grid(row=0, column=0, sticky='nsew', padx=(0, 9)); right.grid(row=0, column=1, sticky='nsew', padx=(9, 0))
    label(left, 'STEP 01', fg='#83a58b', font=(FONT, 9, 'bold')).pack(anchor='w')
    label(left, '녹음 파일 선택', font=(FONT, 17, 'bold')).pack(anchor='w', pady=(5, 0))
    label(left, '글로 바꿀 녹음을 가져와 주세요.', fg=MUTED, font=(FONT, 10)).pack(anchor='w', pady=(3, 9))
    selection = tk.Frame(left, bg=WHITE); selection.pack(fill='x', pady=(3, 6))
    select_btn = button(selection, '＋  녹음 파일 고르기', lambda: select())
    select_btn.pack(anchor='w')
    label(selection, textvariable=chosen, bg=WHITE, fg=MUTED, font=(FONT, 10),
          wraplength=300, justify='left', anchor='w').pack(fill='x', pady=(9, 0))
    settings = tk.Frame(left, bg=WHITE); settings.pack(fill='x', pady=(10, 0))
    label(settings, '음성 인식 모델', font=(FONT, 10, 'bold')).pack(anchor='w')
    model_box = ttk.Combobox(settings, textvariable=model_choice, values=list(model_options), state='readonly', style='Clean.TCombobox'); model_box.pack(fill='x', pady=(3, 6))
    label(settings, '처리 방식', font=(FONT, 10, 'bold')).pack(anchor='w')
    speed_box = ttk.Combobox(settings, textvariable=speed_choice, values=list(speed_choices), state='readonly', style='Clean.TCombobox'); speed_box.pack(fill='x', pady=(3, 0))
    label(left, '빠른 처리는 PC 성능에 따라 속도와 결과가 달라질 수 있어요.', fg=MUTED, font=(FONT, 9), wraplength=300, justify='left').pack(anchor='w', pady=(5, 3))
    run_btn = button(left, '글자로 변환하기  →', lambda: start(), primary=True, state='disabled'); run_btn.pack(fill='x', pady=(4, 0))
    label(right, 'STEP 02', fg='#83a58b', font=(FONT, 9, 'bold')).pack(anchor='w')
    label(right, '변환된 글', font=(FONT, 17, 'bold')).pack(anchor='w', pady=(5, 0))
    label(right, '변환 중에는 인식된 내용이 차례로 나타나요.', fg=MUTED, font=(FONT, 10)).pack(anchor='w', pady=(4, 14))
    info = tk.Frame(right, bg=WHITE); info.pack(fill='x')
    label(info, textvariable=status, fg=GREEN, font=(FONT, 9), wraplength=390, justify='left').pack(side='left', fill='x', expand=True, anchor='w')
    label(info, textvariable=percent, fg=MUTED, font=(FONT, 9)).pack(side='right')
    bar = ttk.Progressbar(right, maximum=100, mode='determinate', style='Clean.Horizontal.TProgressbar'); bar.pack(fill='x', pady=(9, 15))
    text_frame = tk.Frame(right, bg='#f9fbf8', highlightbackground='#e9efe7', highlightthickness=1); text_frame.pack(fill='both', expand=True)
    text = tk.Text(text_frame, wrap='word', bg='#f9fbf8', fg=INK, bd=0, padx=15, pady=15,
                   font=(FONT, 11), height=8, width=20, spacing1=4, spacing3=9, state='disabled', cursor='arrow')
    scroll = ttk.Scrollbar(text_frame, orient='vertical', command=text.yview); text.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y'); text.pack(side='left', fill='both', expand=True)
    actions = tk.Frame(right, bg=WHITE); actions.pack(fill='x', pady=(14, 0))
    label(actions, '완료되면 녹음과 같은 폴더에 저장돼요.', fg=MUTED, font=(FONT, 9)).pack(side='left')
    folder_btn = button(actions, '저장 폴더 열기', lambda: os.startfile(str(state['output'].parent)), state='disabled'); folder_btn.pack(side='right')

    def write_preview(value, clear=False):
        text.configure(state='normal')
        if clear: text.delete('1.0', 'end')
        if value: text.insert('end', value); text.see('end')
        text.configure(state='disabled')

    def select():
        path = filedialog.askopenfilename(title='녹음 파일 선택', parent=app, filetypes=[('녹음 파일', '*.m4a *.mp3 *.wav *.amr *.3gp *.3ga *.aac *.ogg *.flac *.mp4'), ('모든 파일', '*.*')])
        if not path: return
        try: source = validate_source(Path(path))
        except Exception as exc:
            messagebox.showerror('파일 확인', str(exc), parent=app); return
        state['source'] = source; state['output'] = None
        chosen.set(source.name); detail.set('선택 완료 · 녹음은 원본 그대로 보관됩니다.')
        status.set('파일 선택 완료 · 글자로 변환하기를 눌러 주세요.'); percent.set('대기 중')
        bar['value'] = 0; folder_btn.configure(state='disabled'); run_btn.configure(state='normal'); write_preview('', clear=True)

    def work():
        try:
            name = state['requested_model']
            if state['model'] is None or state['model_name'] != name:
                events.put(('status', '음성 인식 모델을 준비하고 있어요.'))
                state['model'] = None; gc.collect()
                state['model'] = load_model(name, lambda m: events.put(('status', m)))
                state['model_name'] = name
            events.put(('status', '녹음을 글로 바꾸고 있어요. 창을 닫지 마세요.'))
            output, seconds = transcribe(state['source'], state['model'], speed=state['requested_speed'],
                progress=lambda n: events.put(('progress', n)), on_segment=lambda row: events.put(('segment', row)))
            events.put(('done', (output, seconds)))
        except Exception as exc: events.put(('error', str(exc)))

    def start():
        if state['busy'] or state['source'] is None: return
        model = model_options[model_choice.get()]
        if needs_download and needs_download(model):
            size = sum(item['size'] for item in manifest[model]['files']) / 1e9
            if not messagebox.askyesno('모델 준비', f'처음 한 번 약 {size:.1f}GB 모델을 내려받습니다.\n인터넷 연결과 저장 공간이 필요합니다.\n녹음 파일은 업로드하지 않습니다.\n계속할까요?', parent=app): return
        state.update(busy=True, requested_model=model, requested_speed=speed_choices[speed_choice.get()], output=None)
        for widget in (select_btn, run_btn, folder_btn, model_box, speed_box): widget.configure(state='disabled')
        write_preview('', clear=True); bar['value'] = 0; percent.set('준비 중'); status.set('변환을 시작합니다. 잠시 기다려 주세요.')
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
                    output, seconds = value; state['output'] = output; finish(); folder_btn.configure(state='normal')
                    status.set(f'변환 완료 · {output.name}'); percent.set('완료')
                    messagebox.showinfo('변환 완료', f'TXT를 저장했습니다.\n\n{output}\n\n원래 녹음을 들으며 내용을 확인해 주세요.', parent=app)
                elif kind == 'error': finish(); status.set('변환하지 못했습니다. 안내를 확인해 주세요.'); percent.set('중단'); messagebox.showerror('변환 확인', value, parent=app)
        except queue.Empty: pass
        app.after(100, poll)

    def close():
        if state['busy'] and not messagebox.askyesno('변환 중', '지금 닫으면 변환이 중단됩니다. 창을 닫을까요?', parent=app): return
        app.destroy()
    app.protocol('WM_DELETE_WINDOW', close); poll(); app.mainloop()
