"""GUI for running pv_tmm."""

import collections
import multiprocessing
import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkf
from tkinter.filedialog import askopenfilename
import time
import sys

import pv_tmm


class MainWindow:
    """Main window object."""

    def __init__(self, master):
        """Construct main window."""
        # redirect stdout and stderr to gui text element
        sys.stdout.write = self.append_output
        sys.stderr.write = self.append_output

        # set up pipe for communicating from child to parent
        self.parent_conn, self.child_conn = multiprocessing.Pipe()

        # create a thread for redirecting subprocess prints to gui element
        self.print_thread = threading.Thread(
            target=self.capture_subprocess_prints, daemon=True
        )
        self.print_thread.start()

        # create thread safe stop notifier
        self.stopper = collections.deque(maxlen=1)
        self.stopper.append(False)

        # set up queue and worker thread for running child processes after button
        # presses
        self.worker_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self.worker, daemon=True)
        self.worker_thread.start()

        self.master = master
        self._make_gui()

    def _make_gui(self):
        """Add widgets to the main window."""
        self.master.title("Transfer matrix simulation")
        self.master.option_add("*Font", "TkDefaultFont")

        self.FONT_HEIGHT = tkf.Font(font="TkDefaultFont").metrics("linespace")
        self.FONT_WIDTH = tkf.Font(font="TkDefaultFont").measure("0")
        self.PADDING = 2 * self.FONT_WIDTH
        self.OUTPUT_WIDTH = 100 * self.FONT_WIDTH

        # set up frames to contain widgets
        self.frm_input = ttk.Frame(master=self.master)
        self.frm_input.pack(
            fill="x", expand=False, padx=self.PADDING, pady=(self.PADDING, 0)
        )

        self.frm_output = ttk.Frame(master=self.master)
        self.frm_output.pack(
            fill="both", expand=True, padx=self.PADDING, pady=self.PADDING
        )

        self.frm_control = ttk.Frame(master=self.master)
        self.frm_control.pack(
            fill="x", expand=False, padx=self.PADDING, pady=(0, self.PADDING)
        )

        # add widgets to input frame
        self.ent_filename = ttk.Entry(master=self.frm_input)
        self.ent_filename.pack(side="left", fill="x", expand=True)

        self.btn_file_dialog = ttk.Button(
            master=self.frm_input, text="Choose file...", command=self.get_config_path
        )
        self.btn_file_dialog.pack(side="right")

        # add widgets to output frame
        self.txt_output = tk.Text(master=self.frm_output, state="disabled")
        self.txt_output.pack(side="left", fill="both", expand=True)

        self.txt_output_scroll = ttk.Scrollbar(
            master=self.frm_output,
            orient="vertical",
            command=self.txt_output.yview,
        )
        self.txt_output_scroll.pack(side="right", fill="y")

        self.txt_output["yscrollcommand"] = self.txt_output_scroll.set

        # add widgets to control frame
        self.progress_bar = ttk.Progressbar(
            master=self.frm_control, orient="horizontal", mode="determinate"
        )
        self.progress_bar.pack(
            side="left", fill="x", expand=True, padx=(0, 10 * self.PADDING)
        )
        self.progress_bar["value"] = 0

        self.btn_stop = ttk.Button(
            master=self.frm_control,
            text="\u25A0 Stop",
            command=self.stop,
            state="disabled",
        )
        self.btn_stop.pack(side="right")

        self.btn_start = ttk.Button(
            master=self.frm_control, text="\u25B6 Start", command=self.start
        )
        self.btn_start.pack(side="right", padx=(0, self.PADDING))

        # enable/disable groups to determine accesss to functionality
        self.start_enable_group = [self.btn_stop]
        self.start_disable_group = [
            self.btn_start,
            self.btn_file_dialog,
            self.ent_filename,
        ]

        # fix minimum size to prevent widgets disappearing
        self.master.update()
        self.master.minsize(self.master.winfo_width(), self.master.winfo_height())

    def append_output(self, text: str):
        """Append text to gui output text element.

        Parameters
        ----------
        text : str
            text to append to gui element.
        """
        self.txt_output.configure(state="normal")
        self.txt_output.insert(tk.END, text)
        self.txt_output.configure(state="disabled")

    def get_config_path(self):
        """Get configuration file path."""
        filepath = askopenfilename(filetypes=[("YAML Files", "*.yaml")])

        if not filepath:
            return

        self.ent_filename.delete(0, tk.END)
        self.ent_filename.insert(0, filepath)

    def worker(self):
        """Run tasks as subprocesses from a dedicated thread."""
        while True:
            msg = self.worker_queue.get()

            # prevent additional button clicks/tasks added to queue
            for widget in self.start_enable_group:
                widget.configure(state="normal")

            for widget in self.start_disable_group:
                widget.configure(state="disabled")

            self.progress_bar["mode"] = "indeterminate"
            self.progress_bar.start(20)

            if msg == "start":
                # run task in a separate process so it can be stopped
                proc = multiprocessing.Process(
                    target=pv_tmm.main,
                    args=(
                        self.ent_filename.get(),
                        self.child_conn,
                    ),
                )
                proc.start()

                # check if stop has been pressed and terminate process if required
                while proc.is_alive():
                    if self.stopper[0]:
                        proc.terminate()
                        print("Task aborted!")
                    time.sleep(0.05)
                    self.txt_output.see("end")

                proc.join()
                print("\n")
            else:
                print(f"Invalid message: {msg}")

            self.worker_queue.task_done()

            # reset button state now task is complete
            for widget in self.start_enable_group:
                widget.configure(state="disabled")

            for widget in self.start_disable_group:
                widget.configure(state="normal")

            self.progress_bar.stop()
            self.progress_bar["mode"] = "determinate"
            self.progress_bar["value"] = 0

            # ensure task ends with stopper reset to false
            self.stopper.append(False)

    def stop(self):
        """Stop the subprocess."""
        self.stopper.append(True)

    def start(self):
        """Start the subprocess."""
        self.worker_queue.put_nowait("start")

    def capture_subprocess_prints(self):
        """Capture prints from a subprocess and add them to a queue."""
        while True:
            print(self.parent_conn.recv())


def main():
    """Run the GUI."""
    app = tk.Tk()
    gui = MainWindow(app)
    app.mainloop()


if __name__ == "__main__":
    main()